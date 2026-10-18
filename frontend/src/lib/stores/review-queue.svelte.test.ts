import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getQueue, listRules } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
import { rule } from '#lib/rules/fixtures.js';
import { queue, section, unit } from '#lib/units/fixtures.js';
import { MARK_RESOLVED } from '#lib/units/patch.js';
import { ReviewQueueStore } from './review-queue.svelte.js';
import { ruleNames } from './rule-names.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	getQueue: vi.fn(),
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

		// the check stays when the cursor visits; only a refresh drops it
		store.visited([2]);
		expect(store.marks.resolved.get(2)).toBe(MARK_RESOLVED);
	});

	it('a consequence mark fades when the cursor visits, the muting and the check do not', async () => {
		vi.mocked(getQueue).mockResolvedValue(
			queue({ pending_review: [plain(1), plain(2), plain(3)] })
		);
		const store = new ReviewQueueStore();
		await store.load();
		store.source.patch({
			entries: [
				entry({ id: 1, unit_key: 1, review_flags: ['unconfirmed'] }),
				entry({ id: 2, unit_key: 2 }),
				entry({ id: 3, unit_key: 3 })
			],
			resolved: [2, 3],
			confirmed: [2]
		});
		expect(store.marks.consequence.has(1)).toBe(true);

		store.visited([1, 2, 3]);

		expect(store.marks.consequence.has(1)).toBe(false);
		expect(store.marks.resolved.has(2)).toBe(true);
		expect(store.marks.resolved.has(3)).toBe(true);
		expect(store.marks.confirmed.has(2)).toBe(true);
		expect(store.marks.confirmed.has(3)).toBe(false);

		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1)] }));
		await store.load();
		expect(store.marks.resolved.size).toBe(0);
	});

	it('reveal visits the unit (its fading marks go) unless told not to (the units just committed)', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1), plain(2)] }));
		const store = new ReviewQueueStore();
		await store.load();
		store.source.patch({
			entries: [
				entry({ id: 1, unit_key: 1, review_flags: ['unconfirmed'] }),
				entry({ id: 2, unit_key: 2, review_flags: ['unconfirmed'] })
			]
		});

		store.source.reveal?.(1, false);
		expect(store.revealed).toBe(1);
		expect(store.marks.consequence.has(1)).toBe(true);

		store.source.reveal?.(2);
		expect(store.marks.consequence.has(2)).toBe(false);
		expect(store.marks.consequence.has(1)).toBe(true);
	});

	it('loads the rule names when a unit shows a rule key', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [unit()] }));
		const store = new ReviewQueueStore();

		await store.load();
		await flush();

		expect(ruleNames.names.loaded).toBe(true);
		expect(ruleNames.names.name(3)).toBe('Rewe');
	});

	it('asks for the rule names again on every load (a refresh included)', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [unit()] }));
		const store = new ReviewQueueStore();

		await store.load();
		await store.load();
		await flush();

		expect(listRules).toHaveBeenCalledTimes(2);
	});
});

describe('ReviewQueueStore: what the panel does to it', () => {
	it('puts the entries a split created into the unit of their anchor, marked resolved', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1), plain(2)] }));
		const store = new ReviewQueueStore();
		await store.load();

		store.patchAffected({
			entries: [entry({ id: 1, unit_key: 1 }), entry({ id: 11, unit_key: 1 })],
			created: [11],
			resolved: [1, 11],
			anchor_entry_id: 1
		});

		expect(store.units[0].entries.map((e) => e.id)).toEqual([1, 11]);
		expect(store.units[1].entries.map((e) => e.id)).toEqual([2]);
		expect(store.marks.resolved.has(11)).toBe(true);
		expect(store.total).toBe(2); // the queue never adds a unit
	});

	it('names its end, takes the panel’s notice and clears it on a reload', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1)] }));
		const store = new ReviewQueueStore();
		await store.load();

		expect(store.source.finishedText).toBe('Review done');
		store.source.notice!('Review done');
		expect(store.notice).toBe('Review done');
		await store.load();
		expect(store.notice).toBeNull();
	});

	it('loads the next page of a section for the panel, and says whether it added units', async () => {
		vi.mocked(getQueue).mockResolvedValueOnce(queue({ pending_review: [plain(1)] }, { total: 2 }));
		const store = new ReviewQueueStore();
		await store.load();
		expect(await store.source.loadMore!()).toBe(false); // no cursor: nothing more

		vi.mocked(getQueue).mockResolvedValueOnce(queue({ pending_review: [plain(1)] }, { total: 2 }));
		await store.load();
		store.sections = store.sections.map((s) =>
			s.kind === 'pending_review' ? { ...s, nextCursor: 'c1', total: 2 } : s
		);
		vi.mocked(getQueue).mockResolvedValueOnce(queue({ pending_review: [plain(2)] }));

		expect(await store.source.loadMore!()).toBe(true);
		expect(store.units.map((u) => u.anchor_entry_id)).toEqual([1, 2]);
	});
});
