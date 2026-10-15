import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, commitUnit, createTag, getUnit, previewUnit } from '#lib/api/index.js';
import { entry, tag } from '#lib/ledger/fixtures.js';
import {
	committed,
	consequence,
	fieldOut,
	preview,
	previewFor,
	previewRowOf,
	problem,
	unit
} from './fixtures.js';
import {
	affectedOf,
	PREVIEW_DELAY_MS,
	UnitDraftFlow,
	type FlowHost
} from './unit-draft-flow.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	previewUnit: vi.fn(),
	commitUnit: vi.fn(),
	createTag: vi.fn(),
	getUnit: vi.fn()
}));

const loaded = unit({
	anchor_entry_id: 1,
	entries: [
		entry({ id: 1, version: 3, unit_key: 1, source_transaction_id: 5, category_id: 10 }),
		entry({
			id: 2,
			version: 4,
			unit_key: 1,
			source_transaction_id: 5,
			amount: { amount: -1000, currency: 'EUR' }
		})
	]
});

function host(): FlowHost & { [K in keyof FlowHost]: ReturnType<typeof vi.fn> } {
	return {
		locale: vi.fn(() => 'en'),
		unitChanged: vi.fn(),
		patch: vi.fn(),
		reloadLookups: vi.fn().mockResolvedValue(undefined),
		addTag: vi.fn(),
		previewed: vi.fn(),
		committed: vi.fn()
	} as never;
}

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

/** Let promises settle, without moving the (fake) clock. */
const settle = async () => {
	for (let i = 0; i < 5; i++) await Promise.resolve();
};

function setup() {
	const h = host();
	const flow = new UnitDraftFlow(h);
	flow.begin(loaded);
	return { flow, h };
}

function error(status: number, code: string, details: unknown = null) {
	return new ApiError(status, code, 'x', details);
}

beforeEach(() => {
	vi.useFakeTimers();
	vi.resetAllMocks();
	vi.mocked(previewUnit).mockImplementation(async (request) => previewFor(loaded, request));
	vi.mocked(getUnit).mockResolvedValue(loaded);
});
afterEach(() => vi.useRealTimers());

describe('opening a unit', () => {
	it('previews the empty draft at once, so the proposals are fresh', async () => {
		const { flow, h } = setup();

		expect(flow.previewStatus).toBe('loading');
		expect(previewUnit).toHaveBeenCalledTimes(1);
		expect(vi.mocked(previewUnit).mock.calls[0][0]).toMatchObject({
			anchor_entry_id: 1,
			entries: [],
			reresolve_all: false
		});
		await settle();

		expect(flow.previewStatus).toBe('ready');
		expect(flow.stale).toBe(false);
		expect(h.previewed).toHaveBeenCalled();
		expect(flow.isDirty).toBe(false);
	});

	it('allows committing without a change: that accepts what is shown', async () => {
		const { flow } = setup();
		await settle();
		expect(flow.commitReason).toBeNull();
	});

	it('says why it cannot commit while the preview is on its way', () => {
		const { flow } = setup();
		expect(flow.commitReason).toBe('Checking what would change…');
	});
});

describe('the live preview', () => {
	it('waits for typing to rest, and asks once', async () => {
		const { flow } = setup();
		await settle();
		vi.mocked(previewUnit).mockClear();

		flow.setText(1, 'note', 'a');
		await vi.advanceTimersByTimeAsync(100);
		flow.setText(1, 'note', 'ab');
		await vi.advanceTimersByTimeAsync(PREVIEW_DELAY_MS - 1);
		expect(previewUnit).not.toHaveBeenCalled();
		expect(flow.stale).toBe(true);

		await vi.advanceTimersByTimeAsync(1);
		expect(previewUnit).toHaveBeenCalledTimes(1);
		expect(vi.mocked(previewUnit).mock.calls[0][0].entries).toEqual([{ id: 1, note: 'ab' }]);
	});

	it('asks at once for a pick', async () => {
		const { flow } = setup();
		await settle();
		vi.mocked(previewUnit).mockClear();

		flow.setField(1, 'category', 11);

		expect(previewUnit).toHaveBeenCalledTimes(1);
		expect(vi.mocked(previewUnit).mock.calls[0][0].entries).toEqual([
			{ id: 1, category: { mode: 'fixed', value: 11 } }
		]);
	});

	it('shows only the latest answer: a slow stale one is discarded', async () => {
		const { flow } = setup();
		await settle();
		const slow = deferred<ReturnType<typeof preview>>();
		vi.mocked(previewUnit).mockImplementationOnce(() => slow.promise);
		flow.setField(1, 'category', 11);
		const latest = preview(loaded, { state: { confirmed: true, reasons: [] } });
		vi.mocked(previewUnit).mockImplementationOnce(async () => latest);
		flow.setField(1, 'category', 12);
		await settle();
		expect(flow.preview).toBe(latest);

		slow.resolve(preview(loaded, { state: { confirmed: false, reasons: ['incomplete'] } }));
		await settle();

		expect(flow.preview).toBe(latest);
	});

	it('aborts the request a newer edit replaces', async () => {
		const { flow } = setup();
		await settle();
		let signal: AbortSignal | undefined;
		vi.mocked(previewUnit).mockImplementationOnce((_draft, s) => {
			signal = s;
			return new Promise(() => {});
		});
		flow.setField(1, 'category', 11);
		flow.setField(1, 'category', 12);
		expect(signal?.aborted).toBe(true);
	});

	it('offers to try again when the preview failed, and holds back the commit', async () => {
		const { flow } = setup();
		await settle();
		vi.mocked(previewUnit).mockRejectedValueOnce(error(0, 'network_error'));
		flow.setField(1, 'category', 11);
		await settle();

		expect(flow.previewStatus).toBe('error');
		expect(flow.commitReason).toBe('The preview could not be loaded.');

		flow.retryPreview();
		await settle();
		expect(flow.previewStatus).toBe('ready');
	});

	it('forgets a pick the lists no longer hold, reloads them and says so', async () => {
		const { flow, h } = setup();
		await settle();
		vi.mocked(previewUnit)
			.mockResolvedValueOnce(
				preview(loaded, {
					problems: [
						problem('stale_reference', {
							entry_id: 1,
							field: 'category_id',
							detail: { id: 11 }
						})
					]
				})
			)
			.mockResolvedValueOnce(preview(loaded));
		flow.setField(1, 'category', 11);
		await settle();

		expect(h.reloadLookups).toHaveBeenCalled();
		expect(flow.draft?.fieldEdit(1, 'category')).toBeUndefined();
		expect(flow.notice?.kind).toBe('conflict');
		expect(previewUnit).toHaveBeenCalledTimes(3); // opened, picked, re-previewed
	});
});

describe('why Commit is disabled', () => {
	it('names a single problem in words, with its remedy', async () => {
		const { flow } = setup();
		await settle();
		vi.mocked(previewUnit).mockResolvedValueOnce(
			preview(loaded, { problems: [problem('residual_zero', { entry_id: 1 })] })
		);
		flow.setField(1, 'category', 11);
		await settle();

		expect(flow.commitReason).toBe(
			'The split leaves nothing for the original entry. Make the new amounts smaller, or remove one.'
		);
	});

	it('counts several', async () => {
		const { flow } = setup();
		await settle();
		vi.mocked(previewUnit).mockResolvedValueOnce(
			preview(loaded, {
				problems: [problem('own_counter_account'), problem('second_transfer')]
			})
		);
		flow.setField(1, 'category', 11);
		await settle();
		expect(flow.commitReason).toBe('2 problems to resolve.');
	});

	it('asks for the amount of a new split, which is not previewed until it has one', async () => {
		const { flow } = setup();
		await settle();
		vi.mocked(previewUnit).mockClear();

		flow.addSplit(1);
		await vi.advanceTimersByTimeAsync(PREVIEW_DELAY_MS);
		await settle();

		expect(flow.commitReason).toBe('Enter the amount of the new split.');
		expect(vi.mocked(previewUnit).mock.calls[0][0].entries).toEqual([]);
		expect(flow.lastAddedSplit).toBe(-1);
	});

	it('refuses an amount that is not one, with the reason under the field', async () => {
		const { flow } = setup();
		await settle();
		flow.addSplit(1);

		flow.setAmountText(-1, 'abc');

		expect(flow.amountErrors[-1]).toBe('This is not an amount.');
		expect(flow.commitReason).toBe('An amount is not valid.');
		flow.setAmountText(-1, '');
		expect(flow.amountErrors[-1]).toBeUndefined(); // nothing typed: only waiting
		expect(flow.commitReason).toBe('Enter the amount of the new split.');
	});
});

describe('split amounts', () => {
	it('takes the entry’s sign and previews the split', async () => {
		const { flow } = setup();
		await settle();
		vi.mocked(previewUnit).mockClear();
		flow.addSplit(1);

		flow.setAmountText(-1, '12.50');
		await vi.advanceTimersByTimeAsync(PREVIEW_DELAY_MS);

		expect(vi.mocked(previewUnit).mock.calls.at(-1)![0].entries).toEqual([
			{ id: -1, source_entry_id: 1, amount: -1250 }
		]);
	});

	it('reallocates a stored entry of a split', async () => {
		const { flow } = setup();
		await settle();
		flow.setAmountText(2, '20');
		expect(flow.draft?.edit(2).amount).toBe(-2000);
	});

	it('removes a split row and forgets what was typed in it', async () => {
		const { flow } = setup();
		await settle();
		flow.addSplit(1);
		flow.setAmountText(-1, 'x');

		flow.removeSplit(-1);

		expect(flow.draft?.splits).toEqual([]);
		expect(flow.amountErrors[-1]).toBeUndefined();
		expect(flow.amountTexts[-1]).toBeUndefined();
	});

	it('offers to split the difference of an unequal pair off the larger leg', async () => {
		const pair = unit({
			anchor_entry_id: 1,
			entries: [
				entry({
					id: 1,
					unit_key: 1,
					source_transaction_id: 5,
					amount: { amount: -5000, currency: 'EUR' }
				}),
				entry({
					id: 2,
					unit_key: 1,
					source_transaction_id: 6,
					amount: { amount: 4900, currency: 'EUR' }
				})
			]
		});
		vi.mocked(previewUnit).mockResolvedValue(preview(pair));
		const h = host();
		const flow = new UnitDraftFlow(h);
		flow.begin(pair);
		await settle();
		const unequal = problem('pair_unequal', {
			entry_id: 1,
			detail: { partner: 2, difference: -100 }
		});

		flow.splitOffDifference(unequal);

		expect(flow.draft?.splits).toEqual([{ id: -1, sourceEntryId: 1, tags: [] }]);
		expect(flow.draft?.edit(-1).amount).toBe(-100);
	});
});

describe('type and re-resolve', () => {
	it('converts at once, re-resolves at once', async () => {
		const { flow } = setup();
		await settle();
		vi.mocked(previewUnit).mockClear();

		flow.convert(1, 'flow');
		flow.reresolve();

		expect(vi.mocked(previewUnit).mock.calls[0][0].entries![0].type).toEqual({
			mode: 'fixed',
			value: 'transfer'
		});
		expect(vi.mocked(previewUnit).mock.calls[1][0].reresolve_all).toBe(true);
		// the pending conversion was re-resolved away; converting again is a new edit
		expect(vi.mocked(previewUnit).mock.calls[1][0].entries).toEqual([]);
		flow.convert(1, 'flow');
		expect(vi.mocked(previewUnit).mock.calls[2][0].entries![0].type).toEqual({
			mode: 'fixed',
			value: 'transfer'
		});
	});

	it('setType makes the entry what was asked, whatever it is now (an entry with no type too)', async () => {
		const { flow } = setup();
		await settle();
		vi.mocked(previewUnit).mockClear();

		flow.setType(1, 'transfer');
		flow.setType(1, 'flow'); // back to what is stored: no edit
		flow.setType(1, 'transfer');

		const types = vi.mocked(previewUnit).mock.calls.map((c) => c[0].entries?.[0]?.type);
		expect(types).toEqual([
			{ mode: 'fixed', value: 'transfer' },
			undefined,
			{ mode: 'fixed', value: 'transfer' }
		]);
	});

	it('x on an entry with no type yet gives a transfer; Flow gives a flow', () => {
		const open = unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, version: 3, unit_key: 1, type: null })]
		});
		const flow = new UnitDraftFlow(host());
		flow.begin(open);
		vi.mocked(previewUnit).mockClear();

		flow.convert(1, null);
		expect(vi.mocked(previewUnit).mock.calls[0][0].entries![0].type).toEqual({
			mode: 'fixed',
			value: 'transfer'
		});
		flow.discard();
		vi.mocked(previewUnit).mockClear();
		flow.setType(1, 'flow');
		expect(vi.mocked(previewUnit).mock.calls[0][0].entries![0].type).toEqual({
			mode: 'fixed',
			value: 'flow'
		});
	});

	it('throws the changes away: the unit as stored, previewed again', async () => {
		const { flow } = setup();
		await settle();
		flow.reresolve();
		expect(flow.isDirty).toBe(true);

		flow.discard();

		expect(flow.isDirty).toBe(false);
	});
});

describe('committing', () => {
	it('sends the draft with the versions the preview named, patches the lists and moves on', async () => {
		const { flow, h } = setup();
		await settle();
		flow.setField(1, 'category', 11);
		await settle();
		const out = committed(loaded, {
			created: { '-1': 77 },
			removed_entry_ids: [9],
			consequences: [
				{ entry_id: 30, kind: 'returns_to_review' },
				{ entry_id: 31, kind: 'left_behind' },
				{ entry_id: 32, kind: 'changed' }
			]
		});
		vi.mocked(commitUnit).mockResolvedValue(out);

		await flow.commit();

		expect(commitUnit).toHaveBeenCalledWith({
			anchor_entry_id: 1,
			entries: [{ id: 1, category: { mode: 'fixed', value: 11 } }],
			removed_entry_ids: [],
			reresolve_all: false,
			versions: { 1: 3, 2: 4 }
		});
		expect(h.patch).toHaveBeenCalledWith({
			entries: loaded.entries,
			resolved: [1, 2],
			confirmed: [1, 2],
			returned_to_review: [30, 31],
			removed_entry_ids: [9],
			created: [77],
			anchor_entry_id: 1
		});
		expect(h.committed).toHaveBeenCalledWith(out, 1);
		// the unit stays spoken for until the panel moves on
		expect(flow.committing).toBe(true);
		expect(flow.commitReason).toBe('The commit is under way.');
	});

	it('refuses to commit while a reason stands', async () => {
		const { flow } = setup();
		await flow.commit();
		expect(commitUnit).not.toHaveBeenCalled();
	});

	it('does not commit twice while one is under way', async () => {
		const { flow } = setup();
		await settle();
		const slow = deferred<ReturnType<typeof committed>>();
		vi.mocked(commitUnit).mockReturnValue(slow.promise);

		const first = flow.commit();
		void flow.commit();
		expect(flow.committing).toBe(true);
		expect(flow.commitReason).toBe('The commit is under way.');
		slow.resolve(committed(loaded));
		await first;

		expect(commitUnit).toHaveBeenCalledTimes(1);
	});
});

describe('affectedOf', () => {
	it('says which rows the action resolved, returned, removed and created', () => {
		const out = committed(loaded, {
			created: { '-2': 5 },
			consequences: [{ entry_id: 8, kind: 'unpaired' }]
		});
		expect(affectedOf(out, 2)).toMatchObject({
			resolved: [1, 2],
			returned_to_review: [8],
			created: [5],
			anchor_entry_id: 2
		});
	});

	it('resolves nothing, and confirms nothing, when the response has no unit', () => {
		const affected = affectedOf(committed(loaded, { units: [] }), 1);
		expect(affected.resolved).toEqual([]);
		expect(affected.confirmed).toEqual([]);
	});

	it('mutes every unit of the response; only the confirmed ones also get the check', () => {
		const out = committed(loaded, {
			units: [
				{
					anchor_entry_id: 1,
					entry_ids: [1, 2],
					state: { confirmed: false, reasons: ['incomplete'] }
				},
				{ anchor_entry_id: 8, entry_ids: [8], state: { confirmed: true, reasons: [] } },
				{ anchor_entry_id: 9, entry_ids: [9, 10], state: { confirmed: true, reasons: [] } }
			]
		});
		const affected = affectedOf(out, 1);
		expect(affected.resolved).toEqual([1, 2, 8, 9, 10]);
		expect(affected.confirmed).toEqual([8, 9, 10]);
	});
});

describe('when a commit fails', () => {
	async function failWith(failure: ApiError) {
		const ctx = setup();
		await settle();
		ctx.flow.setField(1, 'category', 11);
		await settle();
		vi.mocked(commitUnit).mockRejectedValueOnce(failure);
		await ctx.flow.commit();
		return ctx;
	}

	it('conflict: reads the unit again, keeps the draft, previews it anew and offers Reload', async () => {
		const now = unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, version: 9, unit_key: 1, source_transaction_id: 5 })]
		});
		vi.mocked(getUnit).mockResolvedValue(now);
		vi.mocked(previewUnit).mockClear();

		const { flow, h } = await failWith(error(409, 'conflict', { entry_ids: [1] }));
		await settle();

		expect(getUnit).toHaveBeenCalledWith(1);
		expect(h.unitChanged).toHaveBeenCalledWith(now);
		expect(h.patch).toHaveBeenCalledWith({ entries: now.entries });
		expect(flow.draft?.fieldEdit(1, 'category')).toBeDefined(); // kept
		expect(flow.draft?.versions).toEqual({ 1: 9 });
		expect(flow.notice).toMatchObject({ kind: 'conflict', action: { label: 'Reload' } });
		expect(flow.notice?.text).toMatch(/Your changes are kept/);
		expect(previewUnit).toHaveBeenCalled();
		expect(h.committed).not.toHaveBeenCalled();

		flow.notice!.action!.run(); // Reload drops the changes
		expect(flow.isDirty).toBe(false);
	});

	it('unit_moved: the same, keeping what still applies', async () => {
		const now = unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, version: 5, unit_key: 1, source_transaction_id: 5 })]
		});
		vi.mocked(getUnit).mockResolvedValue(now);

		const { flow } = await failWith(error(409, 'unit_moved', { anchor_entry_id: 1 }));

		expect(flow.notice?.text).toMatch(/changed shape/);
		expect(flow.draft?.fieldEdit(1, 'category')).toBeDefined();
		expect(flow.unit).toBe(now);
	});

	it('says the unit is gone when it no longer exists', async () => {
		vi.mocked(getUnit).mockRejectedValue(error(404, 'not_found'));

		const { flow } = await failWith(error(409, 'conflict', { entry_ids: [1] }));

		expect(flow.notice).toMatchObject({ kind: 'error', text: 'This unit no longer exists.' });
	});

	it('stale_reference: reloads the lists, forgets the pick, keeps the rest of the draft', async () => {
		const ctx = setup();
		await settle();
		ctx.flow.setField(1, 'category', 11);
		ctx.flow.setField(1, 'payee', 20);
		await settle();
		vi.mocked(commitUnit).mockRejectedValueOnce(
			error(409, 'stale_reference', { field: 'category_id', entity: 'category', id: 11 })
		);

		await ctx.flow.commit();

		expect(ctx.h.reloadLookups).toHaveBeenCalled();
		expect(ctx.flow.draft?.fieldEdit(1, 'category')).toBeUndefined();
		expect(ctx.flow.draft?.fieldEdit(1, 'payee')).toBeDefined();
		expect(ctx.flow.notice?.text).toMatch(/category you chose no longer exists/);
	});

	it('try_again: keeps the draft and offers the retry', async () => {
		const { flow, h } = await failWith(error(409, 'try_again'));

		expect(flow.notice).toMatchObject({ kind: 'error', action: { label: 'Try again' } });
		expect(flow.isDirty).toBe(true);
		vi.mocked(commitUnit).mockResolvedValueOnce(committed(loaded));
		flow.notice!.action!.run();
		await settle();
		expect(commitUnit).toHaveBeenCalledTimes(2);
		expect(h.committed).toHaveBeenCalled();
	});

	it('422 with problems: shows them in words and previews again', async () => {
		const ctx = setup();
		await settle();
		ctx.flow.setField(1, 'category', 11);
		await settle();
		vi.mocked(previewUnit).mockClear();
		vi.mocked(previewUnit).mockImplementation(() => new Promise(() => {}));
		vi.mocked(commitUnit).mockRejectedValueOnce(
			error(422, 'currency_rule', {
				problems: [
					problem('currency_rule', {
						entry_id: 1,
						field: 'counter_account',
						detail: { required: 'USD', actual: 'EUR' }
					})
				]
			})
		);

		await ctx.flow.commit();

		expect(ctx.flow.commitProblems).toHaveLength(1);
		expect(ctx.flow.problemTexts[0].text.text).toBe(
			'This transfer needs an account in USD, not EUR.'
		);
		expect(previewUnit).toHaveBeenCalledTimes(1);
	});

	it('invalid_draft: says it cannot be committed as it stands', async () => {
		const { flow } = await failWith(error(422, 'invalid_draft', { code: 'amount_zero' }));
		expect(flow.notice?.kind).toBe('error');
		expect(flow.isDirty).toBe(true);
	});

	it('a failure of the connection keeps the draft and offers to try again', async () => {
		const { flow } = await failWith(error(0, 'network_error'));
		expect(flow.notice).toMatchObject({ kind: 'error', action: { label: 'Try again' } });
		expect(flow.isDirty).toBe(true);
		expect(flow.committing).toBe(false);
	});
});

describe('consequences on the way', () => {
	it('keeps the problems and consequences of the last preview while the next is on its way', async () => {
		const { flow } = setup();
		await settle();
		const gone = previewRowOf(entry({ id: 9, version: 2 }));
		vi.mocked(previewUnit).mockResolvedValueOnce(
			preview(loaded, {
				problems: [problem('second_transfer', { entry_id: 2 })],
				consequences: [consequence('deleted', gone)]
			})
		);
		flow.setField(1, 'category', 11);
		await settle();
		flow.setText(1, 'note', 'x'); // debounced: the preview shown is stale now

		expect(flow.stale).toBe(true);
		expect(flow.problems).toHaveLength(1);
		expect(flow.preview?.consequences).toHaveLength(1);
	});
});

describe('what counts as a change', () => {
	const ruled = unit({
		anchor_entry_id: 1,
		entries: [
			entry({
				id: 1,
				version: 3,
				unit_key: 1,
				category_id: 10,
				derivation: { category: { pass: 'rule', basis: { rule_id: 3 } } }
			})
		]
	});

	function start() {
		vi.mocked(previewUnit).mockImplementation(async (request) => previewFor(ruled, request));
		const flow = new UnitDraftFlow(host());
		flow.begin(ruled);
		return flow;
	}

	it('an X whose preview ends in the stored value is no change, once the preview says so', async () => {
		const flow = start();
		await settle();

		flow.clearField(1, 'category');
		expect(flow.draft?.fieldEdit(1, 'category')).toEqual({ mode: 'reresolve' });
		expect(flow.isDirty).toBe(true); // until the preview is the draft's own, an edit counts
		await settle();

		expect(flow.stale).toBe(false);
		expect(flow.isDirty).toBe(false);
	});

	it('an X that ends in another value is a change', async () => {
		const flow = start();
		await settle();
		vi.mocked(previewUnit).mockImplementation(async () => {
			const answer = preview(ruled);
			answer.rows[0].fields.category = fieldOut(null);
			return answer;
		});

		flow.clearField(1, 'category');
		await settle();

		expect(flow.isDirty).toBe(true);
	});

	it('"no payee" over an undecided payee is a change; a pick back to the stored value is not', async () => {
		const flow = start();
		await settle();

		flow.clearField(1, 'payee');
		await settle();
		expect(flow.isDirty).toBe(true);
		expect(flow.draft?.toRequest().entries).toEqual([
			{ id: 1, payee: { mode: 'fixed', value: null } }
		]);

		flow.revertField(1, 'payee');
		await settle();
		expect(flow.isDirty).toBe(false);
	});

	it('other changes stay changes whatever the preview says', async () => {
		const flow = start();
		await settle();
		flow.clearField(1, 'category');
		await settle();
		expect(flow.isDirty).toBe(false);

		flow.setText(1, 'note', 'x');
		expect(flow.isDirty).toBe(true);
	});
});

describe('tags', () => {
	const tagged = unit({
		anchor_entry_id: 1,
		entries: [entry({ id: 1, version: 3, unit_key: 1, tag_ids: [30] })]
	});

	function begin() {
		vi.mocked(previewUnit).mockImplementation(async (request) => previewFor(tagged, request));
		const h = host();
		const flow = new UnitDraftFlow(h);
		flow.begin(tagged);
		return { flow, h };
	}

	it('a tag change makes the draft dirty and goes into the preview request', async () => {
		const { flow } = begin();
		await settle();
		expect(flow.isDirty).toBe(false);

		flow.toggleTag(1, 30);

		expect(flow.isDirty).toBe(true);
		expect(vi.mocked(previewUnit).mock.calls.at(-1)![0].entries).toEqual([
			{ id: 1, tags: { add: [], remove: [30] } }
		]);
		await settle();
		expect(flow.isDirty).toBe(true); // a tag change is no derived-field edit: the preview cannot undo it
	});

	it('a tag-only commit is possible, and sends the change', async () => {
		const { flow, h } = begin();
		await settle();
		flow.toggleTag(1, 99);
		await settle();
		expect(flow.commitReason).toBeNull();
		vi.mocked(commitUnit).mockResolvedValueOnce(committed(tagged));

		await flow.commit();

		expect(vi.mocked(commitUnit).mock.calls[0][0].entries).toEqual([
			{ id: 1, tags: { add: [99], remove: [] } }
		]);
		expect(h.committed).toHaveBeenCalled();
	});

	it('toggling a tag back is no change again', async () => {
		const { flow } = begin();
		await settle();
		flow.toggleTag(1, 99);
		flow.toggleTag(1, 99);
		expect(flow.isDirty).toBe(false);
	});

	it('Reset drops the tag changes', async () => {
		const { flow } = begin();
		await settle();
		flow.toggleTag(1, 30);
		await settle();

		flow.discard();

		expect(flow.isDirty).toBe(false);
		expect(flow.draft?.effectiveTagIds(1)).toEqual([30]);
	});

	it('re-resolve keeps the tag changes', async () => {
		const { flow } = begin();
		await settle();
		flow.toggleTag(1, 30);
		flow.reresolve();
		expect(flow.draft?.tagEdit(1)).toEqual({ add: [], remove: [30] });
	});

	describe('creating a tag from the picker', () => {
		it('creates it at once, lets the lists know and puts it on the entry', async () => {
			const { flow, h } = begin();
			await settle();
			vi.mocked(createTag).mockResolvedValueOnce({ tag: tag({ id: 77, name: 'Lisbon' }) } as never);

			const ok = await flow.createTag(1, 'Lisbon');

			expect(ok).toBe(true);
			expect(createTag).toHaveBeenCalledWith('Lisbon');
			expect(h.addTag).toHaveBeenCalledWith(expect.objectContaining({ id: 77 }));
			expect(flow.draft?.tagEdit(1)).toEqual({ add: [77], remove: [] });
			expect(flow.tagBusy).toBe(false);
		});

		it('a refused creation says why, reloads the lists on a taken name, and changes nothing', async () => {
			const { flow, h } = begin();
			await settle();
			vi.mocked(createTag).mockRejectedValueOnce(
				error(409, 'conflict', { reason: 'duplicate_name' })
			);

			const ok = await flow.createTag(1, 'Lisbon');

			expect(ok).toBe(false);
			expect(h.addTag).not.toHaveBeenCalled();
			expect(h.reloadLookups).toHaveBeenCalled();
			expect(flow.notice).toMatchObject({ kind: 'error' });
			expect(flow.notice?.text).toMatch(/already exists/);
			expect(flow.isDirty).toBe(false);
			expect(flow.tagBusy).toBe(false);
		});

		it('leaves the tag when the draft is cancelled meanwhile', async () => {
			const { flow, h } = begin();
			await settle();
			let done!: (v: unknown) => void;
			vi.mocked(createTag).mockReturnValueOnce(new Promise((r) => (done = r)) as never);

			const pending = flow.createTag(1, 'Lisbon');
			flow.reset();
			done({ tag: tag({ id: 77, name: 'Lisbon' }) });

			expect(await pending).toBe(false);
			expect(h.addTag).toHaveBeenCalled(); // the tag exists now: the lists know it
		});
	});

	describe('a tag that no longer exists', () => {
		it('in a preview: reloads the lists, drops it from the draft, keeps the rest', async () => {
			const { flow, h } = begin();
			await settle();
			flow.toggleTag(1, 30);
			await settle();
			vi.mocked(previewUnit)
				.mockResolvedValueOnce(
					preview(tagged, {
						problems: [
							problem('stale_reference', { field: 'entries[0].tags.add', detail: { id: 99 } })
						]
					})
				)
				.mockResolvedValueOnce(preview(tagged));
			flow.toggleTag(1, 99);
			await settle();

			expect(h.reloadLookups).toHaveBeenCalled();
			expect(flow.draft?.tagEdit(1)).toEqual({ add: [], remove: [30] });
			expect(flow.notice?.kind).toBe('conflict');
		});

		it('on commit: the same, in the words of a tag', async () => {
			const { flow, h } = begin();
			await settle();
			flow.toggleTag(1, 30);
			flow.toggleTag(1, 99);
			await settle();
			vi.mocked(commitUnit).mockRejectedValueOnce(
				error(409, 'stale_reference', { field: 'entries[0].tags.add', entity: 'tag', id: 99 })
			);

			await flow.commit();

			expect(h.reloadLookups).toHaveBeenCalled();
			expect(flow.draft?.tagEdit(1)).toEqual({ add: [], remove: [30] });
			expect(flow.notice?.text).toMatch(/tag you chose no longer exists/);
		});
	});
});
