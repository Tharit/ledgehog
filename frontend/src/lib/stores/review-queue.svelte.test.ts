import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, commitUnit, getQueue, getUnit, listRules, previewUnit } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
import { rule } from '#lib/rules/fixtures.js';
import {
	apiError,
	committed,
	fieldOut,
	preview,
	queue,
	section,
	unit
} from '#lib/units/fixtures.js';
import { MARK_RESOLVED } from '#lib/units/patch.js';
import { ReviewQueueStore } from './review-queue.svelte.js';
import { ruleNames } from './rule-names.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	getQueue: vi.fn(),
	listRules: vi.fn(),
	getUnit: vi.fn(),
	previewUnit: vi.fn(),
	commitUnit: vi.fn()
}));

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const plain = (id: number) =>
	unit({ anchor_entry_id: id, entries: [entry({ id, unit_key: id, derivation: {} })] });

beforeEach(() => {
	vi.resetAllMocks();
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([rule({ id: 3, name: 'Rewe' })]);
});

describe('ReviewQueueStore account filter', () => {
	it('fetches with the accounts, pages with them, and fetches again only when they change', async () => {
		vi.mocked(getQueue).mockResolvedValue({
			...queue(),
			sections: [
				section('pending_review', [plain(1)], { total: 2, next_cursor: 'c1' }),
				section('needs_account', []),
				section('waiting', [])
			],
			total: 2
		});
		const store = new ReviewQueueStore();

		await store.applyAccounts([2, 3]);
		expect(getQueue).toHaveBeenLastCalledWith(expect.objectContaining({ accountIds: [2, 3] }));
		await store.loadMore('pending_review');
		expect(getQueue).toHaveBeenLastCalledWith({
			section: 'pending_review',
			cursor: 'c1',
			accountIds: [2, 3],
			cut: 'counterparty'
		});

		const calls = vi.mocked(getQueue).mock.calls.length;
		await store.applyAccounts([2, 3]);
		expect(getQueue).toHaveBeenCalledTimes(calls);
		await store.applyAccounts([]);
		expect(getQueue).toHaveBeenCalledTimes(calls + 1);
		expect(getQueue).toHaveBeenLastCalledWith(expect.objectContaining({ accountIds: [] }));
	});

	it('fetches on the first apply even with no accounts', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({}));
		const store = new ReviewQueueStore();
		await store.applyAccounts([]);
		expect(getQueue).toHaveBeenCalledTimes(1);
	});
});

describe('ReviewQueueStore cut', () => {
	const group = (key: string | null, label: string | null, count: number, other = false) => ({
		key,
		label,
		count,
		other
	});

	it('passes the cut on the first fetch and on Load more, keeps the first groups, fetches again on a change', async () => {
		const first = group('a', 'Kometa', 3);
		vi.mocked(getQueue).mockResolvedValueOnce({
			...queue(),
			sections: [
				section('pending_review', [plain(1)], {
					total: 3,
					next_cursor: 'c1',
					counterparty_groups: [first, group(null, null, 1, true)]
				}),
				section('needs_account', []),
				section('waiting', [])
			],
			total: 3
		});
		const store = new ReviewQueueStore();
		await store.applyView([], 'counterparty');
		expect(getQueue).toHaveBeenLastCalledWith(expect.objectContaining({ cut: 'counterparty' }));

		vi.mocked(getQueue).mockResolvedValueOnce({
			...queue(),
			sections: [
				section('pending_review', [plain(1), plain(2)], {
					total: 3,
					counterparty_groups: [group('a', 'Relabelled', 9)]
				}),
				section('needs_account', []),
				section('waiting', [])
			],
			total: 3
		});
		await store.loadMore('pending_review');
		expect(getQueue).toHaveBeenLastCalledWith({
			section: 'pending_review',
			cursor: 'c1',
			accountIds: [],
			cut: 'counterparty'
		});
		const pending = store.sections[0];
		expect(pending.units.map((u) => u.anchor_entry_id)).toEqual([1, 2]);
		expect(pending.counterpartyGroups[0]).toEqual(first);
		expect(pending.counterpartyGroups).toHaveLength(2);

		const calls = vi.mocked(getQueue).mock.calls.length;
		await store.applyView([], 'counterparty');
		expect(getQueue).toHaveBeenCalledTimes(calls);
		vi.mocked(getQueue).mockResolvedValue(queue({}));
		await store.applyView([], 'date');
		expect(getQueue).toHaveBeenCalledTimes(calls + 1);
		expect(getQueue).toHaveBeenLastCalledWith(expect.objectContaining({ cut: 'date' }));
	});
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

		expect(getQueue).toHaveBeenLastCalledWith({
			section: 'pending_review',
			cursor: 'c1',
			accountIds: [],
			cut: 'counterparty'
		});
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

describe('ReviewQueueStore: units committed as seen', () => {
	const flow = (id: number, over = {}) =>
		unit({
			anchor_entry_id: id,
			entries: [
				entry({ id, unit_key: id, category_id: 10, review_flags: ['unconfirmed'], ...over })
			]
		});
	const names = { locale: 'en', name: (_f: string, v: unknown) => String(v) };

	async function loaded(units = [flow(1), flow(2), flow(3)], over = {}) {
		vi.mocked(getQueue).mockResolvedValue({
			...queue(),
			sections: [
				section('pending_review', units, over),
				section('needs_account', []),
				section('waiting', [])
			],
			total: units.length
		});
		const store = new ReviewQueueStore();
		await store.load();
		return store;
	}
	/** the server as it was: the unit as it is, its preview untouched, its commit confirming */
	function serve() {
		vi.mocked(getUnit).mockImplementation(async (id) => flow(id));
		vi.mocked(previewUnit).mockImplementation(async (draft) =>
			preview(flow(draft.anchor_entry_id))
		);
		vi.mocked(commitUnit).mockImplementation(async (draft) =>
			committed(flow(draft.anchor_entry_id))
		);
	}

	describe('eligibility', () => {
		it('is a complete interpretation with no answer of the model to come', () => {
			const store = new ReviewQueueStore();
			expect(store.selectionReason(flow(1))).toBeNull();
			expect(store.selectionReason(flow(1, { model_pending: true }))).toBe(
				'The model is still looking'
			);
			expect(
				store.selectionReason(flow(1, { category_id: null, review_flags: ['unclassified'] }))
			).toBe('No category yet');
			expect(
				store.selectionReason({
					...flow(1),
					state: { confirmed: false, reasons: ['unpaired_transfer'] }
				})
			).toBe('Transfer not paired');
			expect(
				store.selectionReason({ ...flow(1), state: { confirmed: false, reasons: ['incomplete'] } })
			).toBe('Not complete yet');
		});

		it('does not take a unit twice, nor one committed already', async () => {
			const store = await loaded();
			store.select([store.units[0]], true);
			store.select([store.units[0]], true);
			expect(store.selected.size).toBe(1);
			store.patchAffected({ entries: store.units[1].entries, resolved: [2] });
			expect(store.select([store.units[1]], true)).toBe('Already committed');
			expect(store.selected.size).toBe(1);
		});

		it('ticks the units that can be and says why when none can', async () => {
			const store = await loaded([flow(1), flow(2, { model_pending: true })]);
			expect(store.select(store.units, true)).toBeNull();
			expect([...store.selected.keys()]).toEqual([1]);
			store.clearSelection();
			expect(store.select([store.units[1]], true)).toBe('The model is still looking');
		});
	});

	describe('the run', () => {
		it('commits each ticked unit in drawn order as the panel would, and patches the rows', async () => {
			serve();
			const store = await loaded();
			store.select(store.units, true);
			await store.commitSelected(names);

			expect(vi.mocked(commitUnit).mock.calls.map(([d]) => d.anchor_entry_id)).toEqual([1, 2, 3]);
			// the panel's commit: the versions the preview named, no draft entry
			expect(vi.mocked(commitUnit).mock.calls[0][0]).toMatchObject({
				anchor_entry_id: 1,
				entries: [],
				versions: { 1: 1 }
			});
			expect([...store.marks.resolved.keys()]).toEqual([1, 2, 3]);
			expect([...store.marks.confirmed.keys()]).toEqual([1, 2, 3]);
			expect(store.selected.size).toBe(0);
			expect(store.progress).toBeNull();
			expect(store.notice).toBe('3 committed');
		});

		it('does not commit a unit whose value moved since its row showed it, and says which', async () => {
			serve();
			vi.mocked(previewUnit).mockImplementation(async (draft) => {
				const u = flow(draft.anchor_entry_id);
				const answer = preview(u);
				if (u.anchor_entry_id === 2) answer.rows[0].fields.category = fieldOut(11);
				return answer;
			});
			const store = await loaded();
			store.select(store.units, true);
			await store.commitSelected(names);

			expect(vi.mocked(commitUnit).mock.calls.map(([d]) => d.anchor_entry_id)).toEqual([1, 3]);
			expect(store.marks.consequence.get(2)).toBe('Changed since you saw it: category is now 11');
			expect(store.marks.resolved.has(2)).toBe(false);
			expect(store.selected.size).toBe(0);
			expect(store.notice).toBe('2 committed · 1 not committed');
		});

		it('does not commit a unit whose description moved', async () => {
			serve();
			vi.mocked(previewUnit).mockImplementation(async (draft) => {
				const answer = preview(flow(draft.anchor_entry_id));
				answer.rows[0].description = 'Something else';
				return answer;
			});
			const store = await loaded([flow(1)]);
			store.select(store.units, true);
			await store.commitSelected(names);
			expect(commitUnit).not.toHaveBeenCalled();
			expect(store.marks.consequence.get(1)).toBe(
				'Changed since you saw it: description is now Something else'
			);
		});

		it('commits when only the basis moved ("2 of 2" where the row said "1 of 1")', async () => {
			serve();
			vi.mocked(previewUnit).mockImplementation(async (draft) => {
				const answer = preview(flow(draft.anchor_entry_id));
				answer.rows[0].fields.category = fieldOut(10, {
					pass: 'history',
					basis: { agree: 2, of: 2, since: '2026-03-14' }
				});
				return answer;
			});
			const store = await loaded([flow(1)]);
			store.select(store.units, true);
			await store.commitSelected(names);
			expect(commitUnit).toHaveBeenCalledTimes(1);
			expect(store.notice).toBe('1 committed');
		});

		it('reports a refusal of the server and goes on with the rest', async () => {
			serve();
			vi.mocked(commitUnit).mockImplementation(async (draft) => {
				if (draft.anchor_entry_id === 1) throw apiError(409, 'conflict');
				return committed(flow(draft.anchor_entry_id));
			});
			const store = await loaded([flow(1), flow(2)]);
			store.select(store.units, true);
			await store.commitSelected(names);

			expect(commitUnit).toHaveBeenCalledTimes(2);
			expect(store.marks.consequence.get(1)).toBe('The unit changed meanwhile.');
			expect(store.marks.resolved.has(2)).toBe(true);
			expect(store.notice).toBe('1 committed · 1 not committed');
		});

		it('names a refused commit by its problem', async () => {
			serve();
			vi.mocked(previewUnit).mockImplementation(async (draft) => ({
				...preview(flow(draft.anchor_entry_id)),
				problems: [
					{ code: 'a', entry_id: null, field: null, detail: {}, suggested_split: null },
					{ code: 'b', entry_id: null, field: null, detail: {}, suggested_split: null }
				]
			}));
			const store = await loaded([flow(1)]);
			store.select(store.units, true);
			await store.commitSelected(names);
			expect(commitUnit).not.toHaveBeenCalled();
			expect(store.marks.consequence.get(1)).toBe('2 problems to resolve.');
		});

		it('says how far it is, and starts no second run', async () => {
			serve();
			let release!: () => void;
			vi.mocked(commitUnit).mockImplementationOnce(async (draft) => {
				await new Promise<void>((resolve) => (release = resolve));
				return committed(flow(draft.anchor_entry_id));
			});
			const store = await loaded([flow(1), flow(2)]);
			store.select(store.units, true);
			const run = store.commitSelected(names);
			await vi.waitFor(() => expect(store.progress).toEqual({ done: 0, total: 2 }));
			await store.commitSelected(names);
			expect(getUnit).toHaveBeenCalledTimes(1);
			release();
			await run;
			expect(commitUnit).toHaveBeenCalledTimes(2);
		});

		it('is void once the queue is loaded again', async () => {
			serve();
			let release!: () => void;
			vi.mocked(commitUnit).mockImplementationOnce(async (draft) => {
				await new Promise<void>((resolve) => (release = resolve));
				return committed(flow(draft.anchor_entry_id));
			});
			const store = await loaded([flow(1), flow(2)]);
			store.select(store.units, true);
			const run = store.commitSelected(names);
			await vi.waitFor(() => expect(release).toBeDefined());
			await store.load();
			release();
			await run;
			expect(commitUnit).toHaveBeenCalledTimes(1);
			expect(store.notice).toBeNull();
		});
	});

	describe('the ticks', () => {
		it('are cleared by a refresh and a change of cut, and kept by Load more', async () => {
			const store = await loaded([flow(1), flow(2)], { total: 3, next_cursor: 'c1' });
			store.select([store.units[0]], true);
			vi.mocked(getQueue).mockResolvedValue({
				...queue(),
				sections: [
					section('pending_review', [flow(3)]),
					section('needs_account', []),
					section('waiting', [])
				]
			});
			await store.loadMore('pending_review');
			expect([...store.selected.keys()]).toEqual([1]);

			await store.applyView([], 'counterparty');
			expect(store.selected.size).toBe(0);
			store.select([store.units[0]], true);
			await store.load();
			expect(store.selected.size).toBe(0);
		});
	});
});
