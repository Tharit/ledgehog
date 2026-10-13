import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getNewUnitCount, getQueue, listRules } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
import { rule } from '#lib/rules/fixtures.js';
import { queue, section, unit } from '#lib/units/fixtures.js';
import { MARK_RESOLVED } from '#lib/units/patch.js';
import { ReviewQueueStore } from './review-queue.svelte.js';
import { ruleNames } from './rule-names.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	getQueue: vi.fn(),
	getNewUnitCount: vi.fn(),
	listRules: vi.fn()
}));

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const plain = (id: number) =>
	unit({ anchor_entry_id: id, entries: [entry({ id, unit_key: id, derivation: {} })] });

beforeEach(() => {
	vi.resetAllMocks();
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([rule({ id: 3, name: 'Rewe' })]);
});

describe('ReviewQueueStore', () => {
	it('loads the three sections, always in the same order', async () => {
		vi.mocked(getQueue).mockResolvedValue(
			queue({ pending_review: [plain(1), plain(2)], waiting: [plain(3)] })
		);
		const store = new ReviewQueueStore();

		await store.load();

		expect(store.status).toBe('ready');
		expect(store.sections.map((s) => [s.kind, s.total])).toEqual([
			['pending_review', 2],
			['needs_account', 0],
			['waiting', 1]
		]);
		expect(store.total).toBe(3);
		expect(store.units.map((u) => u.anchor_entry_id)).toEqual([1, 2, 3]);
	});

	it('keeps the error to retry', async () => {
		vi.mocked(getQueue).mockRejectedValue(new ApiError(0, 'network_error', 'x'));
		const store = new ReviewQueueStore();

		await store.load();

		expect(store.status).toBe('error');
		expect(store.error?.code).toBe('network_error');
	});

	it('keeps the queue it holds when a refresh fails', async () => {
		vi.mocked(getQueue).mockResolvedValueOnce(queue({ pending_review: [plain(1)] }));
		const store = new ReviewQueueStore();
		await store.load();
		vi.mocked(getQueue).mockRejectedValueOnce(new ApiError(0, 'network_error', 'x'));

		await store.load();

		expect(store.status).toBe('ready');
		expect(store.units).toHaveLength(1);
	});

	it('appends a section by its keyset cursor, never duplicating a unit', async () => {
		vi.mocked(getQueue).mockResolvedValueOnce({
			...queue(),
			sections: [
				section('pending_review', [plain(1), plain(2)], { total: 4, next_cursor: 'c1' }),
				section('needs_account', []),
				section('waiting', [])
			],
			total: 4
		});
		const store = new ReviewQueueStore();
		await store.load();
		vi.mocked(getQueue).mockResolvedValueOnce({
			...queue(),
			sections: [section('pending_review', [plain(2), plain(3), plain(4)], { total: 4 })]
		});

		await store.loadMore('pending_review');

		expect(getQueue).toHaveBeenLastCalledWith({ section: 'pending_review', cursor: 'c1' });
		const pending = store.sections[0];
		expect(pending.units.map((u) => u.anchor_entry_id)).toEqual([1, 2, 3, 4]);
		expect(pending.nextCursor).toBeNull();
	});

	it('says why a page could not be loaded and keeps what it holds', async () => {
		vi.mocked(getQueue).mockResolvedValueOnce({
			...queue(),
			sections: [
				section('pending_review', [plain(1)], { total: 2, next_cursor: 'c1' }),
				section('needs_account', []),
				section('waiting', [])
			]
		});
		const store = new ReviewQueueStore();
		await store.load();
		vi.mocked(getQueue).mockRejectedValueOnce(new ApiError(0, 'network_error', 'x'));

		await store.loadMore('pending_review');

		expect(store.sections[0].moreError?.code).toBe('network_error');
		expect(store.sections[0].units).toHaveLength(1);
		expect(store.sections[0].loadingMore).toBe(false);
	});

	describe('new units', () => {
		it('counts the units that arrived since the snapshot, and refetches nothing', async () => {
			vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1)] }));
			vi.mocked(getNewUnitCount).mockResolvedValue({ new_count: 12, snapshot: 'snap-2' });
			const store = new ReviewQueueStore();
			await store.load();

			await store.checkNew();

			expect(getNewUnitCount).toHaveBeenCalledWith('snap-1', expect.any(AbortSignal));
			expect(store.newCount).toBe(12);
			expect(getQueue).toHaveBeenCalledTimes(1);
			expect(store.units).toHaveLength(1);
		});

		it('counts always against the snapshot of the queue shown, and a refresh resets it', async () => {
			vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1)] }));
			vi.mocked(getNewUnitCount).mockResolvedValue({ new_count: 2, snapshot: 'snap-2' });
			const store = new ReviewQueueStore();
			await store.load();
			await store.checkNew();
			await store.checkNew();
			expect(vi.mocked(getNewUnitCount).mock.calls.map((c) => c[0])).toEqual(['snap-1', 'snap-1']);

			await store.load();

			expect(store.newCount).toBe(0);
		});

		it('says nothing when the count cannot be had', async () => {
			vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1)] }));
			vi.mocked(getNewUnitCount).mockRejectedValue(new ApiError(0, 'network_error', 'x'));
			const store = new ReviewQueueStore();
			await store.load();

			await store.checkNew();

			expect(store.newCount).toBe(0);
		});

		it('does not ask before the queue has loaded', async () => {
			const store = new ReviewQueueStore();

			await store.checkNew();

			expect(getNewUnitCount).not.toHaveBeenCalled();
		});
	});

	describe('as the panel source', () => {
		async function loaded() {
			vi.mocked(getQueue).mockResolvedValue({
				...queue(),
				sections: [
					section(
						'pending_review',
						[
							plain(1),
							unit({
								anchor_entry_id: 2,
								entries: [entry({ id: 2, unit_key: 2 }), entry({ id: 5, unit_key: 2 })]
							})
						],
						{ total: 212 }
					),
					section('needs_account', []),
					section('waiting', [plain(7)], { total: 2 })
				],
				total: 214
			});
			const store = new ReviewQueueStore();
			await store.load();
			return store;
		}

		it('steps in queue order across the sections, by the anchor of the next unit', async () => {
			const store = await loaded();

			expect(store.source.neighbour(1, 1)).toBe(2);
			expect(store.source.neighbour(5, 1)).toBe(7); // an entry of the unit, not its anchor
			expect(store.source.neighbour(7, -1)).toBe(2);
			expect(store.source.neighbour(1, -1)).toBeNull();
			expect(store.source.neighbour(7, 1)).toBeNull();
			expect(store.source.neighbour(99, 1)).toBeNull();
		});

		it('knows the position of a unit among all of them', async () => {
			const store = await loaded();

			expect(store.source.position?.(5)).toEqual({ index: 2, total: 214 });
			expect(store.source.position?.(99)).toBeNull();
		});
	});

	it('patches entries in place and marks them; the units never move', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1), plain(2)] }));
		const store = new ReviewQueueStore();
		await store.load();

		store.source.patch({
			entries: [entry({ id: 2, unit_key: 2, note: 'done', review_flags: [] })],
			resolved: [2]
		});

		expect(store.units.map((u) => u.anchor_entry_id)).toEqual([1, 2]);
		expect(store.units[1].entries[0].note).toBe('done');
		expect(store.marks.resolved.get(2)).toBe(MARK_RESOLVED);

		store.visited([2]);
		expect(store.marks.resolved.size).toBe(0);
	});

	it('loads the rule names when a unit shows a rule key', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [unit()] }));
		const store = new ReviewQueueStore();

		await store.load();
		await flush();

		expect(ruleNames.names.loaded).toBe(true);
		expect(ruleNames.names.name(3)).toBe('Rewe');
	});
});
