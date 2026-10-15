import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	ApiError,
	createRule,
	getRule,
	listAccounts,
	listCategories,
	listPayees,
	listRules,
	updateRule
} from '#lib/api/index.js';
import { newConditionRow, type ConditionField, type ConditionOp } from '#lib/rules/conditions.js';
import { preview, previewList, previewRow, rule } from '#lib/rules/fixtures.js';
import { PREVIEW_PAGE, RuleEditorStore } from './rule-editor.svelte.js';
import { ruleNames } from './rule-names.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	createRule: vi.fn(),
	updateRule: vi.fn(),
	getRule: vi.fn(),
	listRules: vi.fn(),
	listAccounts: vi.fn(),
	listCategories: vi.fn(),
	listPayees: vi.fn()
}));

function out(p = preview(), over = {}) {
	return { dry_run: true, rule: null, preview: p, settle: null, settle_breakdown: null, ...over };
}

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((res) => {
		resolve = res;
	});
	return { promise, resolve };
}

function failure(status: number, code: string, details: unknown = null) {
	return new ApiError(status, code, 'x', details);
}

const DEBOUNCE = 400;

/** a condition row; the counterparty name starting with `value` unless told otherwise */
function cond(
	value: string,
	field: ConditionField = 'counterparty_name',
	op: ConditionOp = 'starts_with'
) {
	return newConditionRow({ field, op, value });
}

/** an editor for a stored rule, loaded and previewed */
async function editing(p = preview({ matches: previewList([previewRow()], 1) })) {
	vi.mocked(getRule).mockResolvedValue(rule({ id: 5 }));
	vi.mocked(updateRule).mockResolvedValue(out(p));
	const store = new RuleEditorStore({ ruleId: 5 });
	await store.init();
	await vi.advanceTimersByTimeAsync(0);
	return store;
}

beforeEach(() => {
	vi.useFakeTimers();
	vi.resetAllMocks();
	vi.mocked(listAccounts).mockResolvedValue([]);
	vi.mocked(listCategories).mockResolvedValue([]);
	vi.mocked(listPayees).mockResolvedValue([]);
	vi.mocked(listRules).mockResolvedValue([]);
});

afterEach(() => {
	vi.useRealTimers();
});

describe('RuleEditorStore: loading', () => {
	it('starts a new rule blank, with no preview to ask for', async () => {
		const store = new RuleEditorStore({ ruleId: null });

		await store.init();

		expect(store.loadStatus).toBe('ready');
		expect(store.form.name).toBe('');
		expect(store.previewStatus).toBe('idle');
		expect(createRule).not.toHaveBeenCalled();
	});

	it('loads a stored rule into the form and previews it at once', async () => {
		const store = await editing();

		expect(store.loadStatus).toBe('ready');
		expect(store.form).toMatchObject({ name: 'Landlord', sets: 'category', target: 10 });
		expect(updateRule).toHaveBeenCalledTimes(1);
		const [id, fields, controls] = vi.mocked(updateRule).mock.calls[0];
		expect(id).toBe(5);
		expect(fields).toMatchObject({
			category_id: 10,
			conditions: [{ field: 'counterparty_name', op: 'starts_with', value: 'Landlord' }]
		});
		expect(controls).toMatchObject({ dryRun: true, limit: PREVIEW_PAGE });
		expect(controls?.expectedCount).toBeUndefined();
		expect(store.previewStatus).toBe('ready');
		expect(store.previewCurrent).toBe(true);
	});

	it('says a rule that is gone is missing', async () => {
		vi.mocked(getRule).mockRejectedValue(failure(404, 'not_found'));
		const store = new RuleEditorStore({ ruleId: 9 });

		await store.init();

		expect(store.loadStatus).toBe('missing');
	});

	it('offers a retry for a rule that could not be loaded', async () => {
		vi.mocked(getRule).mockRejectedValue(failure(0, 'network_error'));
		const store = new RuleEditorStore({ ruleId: 9 });

		await store.init();

		expect(store.loadStatus).toBe('error');
	});
});

describe('RuleEditorStore: the debounced preview', () => {
	it('asks once, after the last edit, with dry_run and the form as the body', async () => {
		vi.mocked(createRule).mockResolvedValue(out());
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();

		store.edit({ target: 3, conditions: [cond('P')] });
		await vi.advanceTimersByTimeAsync(DEBOUNCE - 50);
		store.edit({ conditions: [cond('PAY')] });
		await vi.advanceTimersByTimeAsync(DEBOUNCE - 50);
		expect(createRule).not.toHaveBeenCalled();
		expect(store.previewStatus).toBe('loading');

		await vi.advanceTimersByTimeAsync(100);

		expect(createRule).toHaveBeenCalledTimes(1);
		const [fields, controls] = vi.mocked(createRule).mock.calls[0];
		expect(fields).toMatchObject({
			sets: 'category',
			category_id: 3,
			conditions: [{ field: 'counterparty_name', op: 'starts_with', value: 'PAY' }]
		});
		expect(fields.name).toBe('Untitled rule');
		expect(controls).toMatchObject({ dryRun: true, limit: PREVIEW_PAGE });
		expect(store.previewStatus).toBe('ready');
	});

	it('asks for nothing until there is a target and a condition', async () => {
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();

		store.edit({ target: 3 });
		await vi.advanceTimersByTimeAsync(DEBOUNCE * 2);

		expect(createRule).not.toHaveBeenCalled();
		expect(store.previewStatus).toBe('idle');
	});

	it('asks at once for a choice, without the pause', async () => {
		vi.mocked(createRule).mockResolvedValue(out());
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();
		store.edit({ target: 3 });

		store.edit({ conditions: [cond('PAYPAL *')] }, true);
		await vi.advanceTimersByTimeAsync(0);

		expect(createRule).toHaveBeenCalledTimes(1);
	});

	it('discards an answer that a newer edit has superseded', async () => {
		const first = deferred<ReturnType<typeof out>>();
		vi.mocked(createRule)
			.mockReturnValueOnce(first.promise)
			.mockResolvedValueOnce(out(preview({ would_confirm: 7 })));
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();
		store.edit({ target: 3, conditions: [cond('A')] });
		await vi.advanceTimersByTimeAsync(DEBOUNCE);

		store.edit({ conditions: [cond('AB')] });
		await vi.advanceTimersByTimeAsync(DEBOUNCE);
		first.resolve(out(preview({ would_confirm: 1 })));
		await vi.advanceTimersByTimeAsync(0);

		expect(store.preview?.would_confirm).toBe(7);
		expect(store.previewCurrent).toBe(true);
	});

	it('keeps the held preview, not current, while the next one is on its way', async () => {
		const store = await editing(preview({ would_confirm: 2 }));

		store.edit({ conditions: [cond('SEPA', 'booking_text', 'equals')] });

		expect(store.preview?.would_confirm).toBe(2);
		expect(store.previewStatus).toBe('loading');
		expect(store.previewCurrent).toBe(false);
	});

	it('shows an invalid regex at its row and holds no preview', async () => {
		vi.mocked(createRule).mockRejectedValue(
			failure(422, 'invalid_rule', [
				{
					location: ['body', 'conditions[0].value'],
					message: 'conditions[0]: the regex does not compile',
					type: 'invalid_rule'
				}
			])
		);
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();

		store.edit({ target: 3, conditions: [cond('(', 'purpose', 'regex')] });
		await vi.advanceTimersByTimeAsync(DEBOUNCE);

		expect(store.previewStatus).toBe('error');
		expect(store.preview).toBeNull();
		expect(store.fieldErrors.rows).toEqual({ 0: 'The regex does not compile' });
		expect(store.canSave).toBe(false);
	});

	it('clears a row error as soon as the form is edited', async () => {
		vi.mocked(createRule).mockRejectedValue(
			failure(422, 'invalid_rule', [
				{ location: ['body', 'conditions[0].value'], message: 'bad', type: 'invalid_rule' }
			])
		);
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();
		store.edit({ target: 3, conditions: [cond('(', 'purpose', 'regex')] });
		await vi.advanceTimersByTimeAsync(DEBOUNCE);

		store.edit({ conditions: [cond('()', 'purpose', 'regex')] });

		expect(store.fieldErrors.rows).toBeUndefined();
	});

	it('says so, with a way to retry, when the server cannot be reached', async () => {
		vi.mocked(createRule).mockRejectedValue(failure(0, 'network_error'));
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();

		store.edit({ target: 3, conditions: [cond('P')] });
		await vi.advanceTimersByTimeAsync(DEBOUNCE);

		expect(store.error?.kind).toBe('network');
		expect(store.notice?.error).toBe(true);
		vi.mocked(createRule).mockResolvedValue(out());
		store.refreshPreview();
		await vi.advanceTimersByTimeAsync(0);
		expect(store.previewStatus).toBe('ready');
	});

	it('forgets the rows of "show more" when the preview is taken again', async () => {
		const store = await editing(
			preview({ matches: previewList([previewRow({ entry_id: 1 })], 2) })
		);
		vi.mocked(updateRule).mockResolvedValue(
			out(preview({ matches: previewList([previewRow({ entry_id: 2 })], 2) }))
		);
		await store.more('matches');
		expect(store.rowsOf('matches').map((r) => r.entry_id)).toEqual([1, 2]);

		store.edit({ conditions: [cond('x', 'booking_text', 'equals')] }, true);
		await vi.advanceTimersByTimeAsync(0);

		expect(store.rowsOf('matches').map((r) => r.entry_id)).toEqual([2]);
	});
});

describe('RuleEditorStore: show more', () => {
	it('asks for the next page at the offset of the rows held and appends one list', async () => {
		const store = await editing(
			preview({
				matches: previewList([previewRow({ entry_id: 1 })], 3),
				different_value: previewList([previewRow({ entry_id: 8 })], 2)
			})
		);
		vi.mocked(updateRule).mockResolvedValue(
			out(
				preview({
					matches: previewList([previewRow({ entry_id: 2 })], 3),
					different_value: previewList([previewRow({ entry_id: 9 })], 2)
				})
			)
		);

		await store.more('matches');

		expect(vi.mocked(updateRule).mock.calls.at(-1)![2]).toMatchObject({
			dryRun: true,
			offset: 1,
			limit: PREVIEW_PAGE
		});
		expect(store.rowsOf('matches').map((r) => r.entry_id)).toEqual([1, 2]);
		expect(store.rowsOf('different_value').map((r) => r.entry_id)).toEqual([8]);
	});

	it('starts over when the totals moved meanwhile', async () => {
		const store = await editing(preview({ matches: previewList([previewRow()], 3) }));
		vi.mocked(updateRule).mockResolvedValue(
			out(preview({ matches: previewList([previewRow({ entry_id: 2 })], 5) }))
		);

		await store.more('matches');
		await vi.advanceTimersByTimeAsync(0);

		expect(store.notice?.text).toMatch(/changed/);
		expect(store.preview?.matches.total).toBe(5);
		expect(store.rowsOf('matches')).toHaveLength(1);
	});
});

describe('RuleEditorStore: saving', () => {
	it('is not possible before a preview of this very form', async () => {
		const store = await editing();
		expect(store.canSave).toBe(false); // unchanged

		store.edit({ conditions: [cond('SEPA', 'booking_text', 'equals')] });
		expect(store.saveBlocked).toMatch(/preview/);

		await vi.advanceTimersByTimeAsync(DEBOUNCE);
		expect(store.canSave).toBe(true);

		store.edit({ conditions: [cond('SEPA2', 'booking_text', 'equals')] });
		expect(store.canSave).toBe(false);
	});

	it('is not possible without a name', async () => {
		vi.mocked(createRule).mockResolvedValue(out());
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();
		store.edit({ target: 3, conditions: [cond('P')] }, true);
		await vi.advanceTimersByTimeAsync(0);

		expect(store.saveBlocked).toMatch(/name/);
		store.edit({ name: 'Rent' });
		await vi.advanceTimersByTimeAsync(DEBOUNCE);
		expect(store.canSave).toBe(true);
	});

	it('writes with the previewed count and reports what settled', async () => {
		const store = await editing(preview({ matches: previewList([previewRow()], 12) }));
		store.edit({ conditions: [cond('SEPA', 'booking_text', 'equals')] });
		await vi.advanceTimersByTimeAsync(DEBOUNCE);
		vi.mocked(updateRule).mockResolvedValue(
			out(preview(), {
				dry_run: false,
				rule: rule({ id: 5, name: 'Landlord' }),
				settle: { touched_entry_ids: [1, 2, 3], error: null },
				settle_breakdown: { total: 3, this_rule: 2, history: 1, other_rules: 0, other: 0 }
			})
		);

		const result = await store.save();

		const [id, fields, controls] = vi.mocked(updateRule).mock.calls.at(-1)!;
		expect(id).toBe(5);
		expect(fields).toMatchObject({
			conditions: [{ field: 'booking_text', op: 'equals', value: 'SEPA' }],
			name: 'Landlord'
		});
		expect(controls).toMatchObject({ expectedCount: 12 });
		expect(controls?.dryRun).toBeFalsy();
		expect(result).toEqual({
			rule: expect.objectContaining({ id: 5 }),
			breakdown: { total: 3, thisRule: 2, history: 1, otherRules: 0, other: 0 },
			settleFailed: false
		});
	});

	it('marks the rule names held as old once a rule is written', async () => {
		const store = await editing(preview({ matches: previewList([previewRow()], 12) }));
		store.edit({ conditions: [cond('SEPA', 'booking_text', 'equals')] });
		await vi.advanceTimersByTimeAsync(DEBOUNCE);
		vi.mocked(updateRule).mockResolvedValue(
			out(preview(), { dry_run: false, rule: rule({ id: 5 }), settle: null })
		);
		await ruleNames.refresh();
		expect(ruleNames.names.loaded).toBe(true);

		await store.save();

		expect(ruleNames.names.loaded).toBe(false);
	});

	it('creates a new rule with the count of its preview', async () => {
		vi.mocked(createRule).mockResolvedValueOnce(
			out(preview({ matches: previewList([previewRow()], 4) }))
		);
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();
		store.edit({ name: 'Rent', target: 3, conditions: [cond('Landlord')] }, true);
		await vi.advanceTimersByTimeAsync(0);
		vi.mocked(createRule).mockResolvedValueOnce(
			out(preview(), { dry_run: false, rule: rule({ id: 77, name: 'Rent' }), settle: null })
		);

		const result = await store.save();

		expect(vi.mocked(createRule).mock.calls.at(-1)![1]).toMatchObject({ expectedCount: 4 });
		expect(result?.rule.id).toBe(77);
		expect(result?.breakdown).toBeNull();
	});

	it('refreshes the preview and says so when the result moved', async () => {
		const store = await editing(preview({ matches: previewList([previewRow()], 12) }));
		store.edit({ conditions: [cond('SEPA', 'booking_text', 'equals')] });
		await vi.advanceTimersByTimeAsync(DEBOUNCE);
		vi.mocked(updateRule)
			.mockRejectedValueOnce(
				failure(409, 'conflict', { reason: 'filter_result_changed', expected: 12, actual: 14 })
			)
			.mockResolvedValue(out(preview({ matches: previewList([previewRow()], 14) })));

		const result = await store.save();
		await vi.advanceTimersByTimeAsync(0);

		expect(result).toBeNull();
		expect(store.notice?.text).toMatch(/12 entries before, 14 now/);
		expect(store.preview?.matches.total).toBe(14);
		expect(store.canSave).toBe(true);
	});

	it('shows a taken name at the name and holds no preview', async () => {
		const store = await editing();
		store.edit({ name: 'Taken' });
		await vi.advanceTimersByTimeAsync(DEBOUNCE);
		vi.mocked(updateRule).mockRejectedValue(failure(409, 'conflict', { reason: 'duplicate_name' }));

		await store.save();

		expect(store.fieldErrors.name).toMatch(/already exists/);
		expect(store.canSave).toBe(false);
	});

	it('reloads the lists and drops a target that is gone on a stale reference', async () => {
		const store = await editing();
		store.edit({ conditions: [cond('SEPA', 'booking_text', 'equals')] });
		await vi.advanceTimersByTimeAsync(DEBOUNCE);
		vi.mocked(updateRule).mockRejectedValue(
			failure(409, 'stale_reference', { field: 'category_id', entity: 'category', id: 10 })
		);
		vi.mocked(listCategories).mockClear();

		await store.save();
		await vi.advanceTimersByTimeAsync(DEBOUNCE);

		expect(listCategories).toHaveBeenCalled();
		expect(store.form.target).toBeNull();
		expect(store.form.conditions[0].value).toBe('SEPA');
		expect(store.fieldErrors.target).toMatch(/no longer exists/);
		expect(store.notice?.text).toMatch(/Category you chose no longer exists/);
	});

	it('keeps a payee row whose payee is gone, flagged on that row', async () => {
		const store = await editing();
		store.edit({
			conditions: [
				cond(''),
				newConditionRow({ field: 'payee', op: 'is', value: '77' }),
				cond('SEPA', 'booking_text', 'equals')
			]
		});
		await vi.advanceTimersByTimeAsync(DEBOUNCE);
		vi.mocked(updateRule).mockRejectedValue(
			failure(409, 'stale_reference', { field: 'conditions[0].value', entity: 'payee', id: 77 })
		);

		await store.save();
		await vi.advanceTimersByTimeAsync(DEBOUNCE);

		// request position 0 is the editor's row 1: the blank first row was left out
		expect(store.form.conditions.map((c) => c.value)).toEqual(['', '77', 'SEPA']);
		expect(store.fieldErrors.rows).toEqual({ 1: 'This payee no longer exists.' });
	});

	it('starts a row over when it moves to or from the payee field', async () => {
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();
		store.editCondition(0, { value: 'x' });

		store.editCondition(0, { field: 'payee' });
		expect(store.form.conditions[0]).toMatchObject({ field: 'payee', op: 'is', value: '' });

		store.editCondition(0, { value: '4' });
		store.editCondition(0, { field: 'purpose' });
		expect(store.form.conditions[0]).toMatchObject({ field: 'purpose', op: 'contains', value: '' });
	});

	it('keeps the preview after a network failure, so saving can be tried again', async () => {
		const store = await editing();
		store.edit({ conditions: [cond('SEPA', 'booking_text', 'equals')] });
		await vi.advanceTimersByTimeAsync(DEBOUNCE);
		vi.mocked(updateRule).mockRejectedValue(failure(0, 'network_error'));

		await store.save();

		expect(store.notice?.error).toBe(true);
		expect(store.canSave).toBe(true);
	});
});

describe('RuleEditorStore: the condition rows', () => {
	it('starts with one blank row', async () => {
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();

		expect(store.form.conditions).toHaveLength(1);
		expect(store.form.conditions[0].value).toBe('');
	});

	it('adds a row without asking for a preview: a blank row changes nothing', async () => {
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();
		store.edit({ target: 3, conditions: [cond('P')] }, true);
		await vi.advanceTimersByTimeAsync(0);
		vi.mocked(createRule).mockClear();

		store.addCondition();
		await vi.advanceTimersByTimeAsync(DEBOUNCE * 2);

		expect(store.form.conditions).toHaveLength(2);
		expect(createRule).not.toHaveBeenCalled();
	});

	it('edits one row: a text edit waits for the pause, a choice does not', async () => {
		vi.mocked(createRule).mockResolvedValue(out());
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();
		store.edit({ target: 3 });

		store.editCondition(0, { value: 'REWE' });
		await vi.advanceTimersByTimeAsync(DEBOUNCE - 50);
		expect(createRule).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(100);
		expect(createRule).toHaveBeenCalledTimes(1);

		store.editCondition(0, { op: 'equals' });
		await vi.advanceTimersByTimeAsync(0);
		expect(createRule).toHaveBeenCalledTimes(2);
		expect(vi.mocked(createRule).mock.calls[1][0].conditions).toEqual([
			{ field: 'counterparty_name', op: 'equals', value: 'REWE' }
		]);
	});

	it('removes a row and asks again; the last row stays, blank', async () => {
		vi.mocked(createRule).mockResolvedValue(out());
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();
		store.edit({ target: 3, conditions: [cond('A'), cond('B', 'purpose', 'contains')] }, true);
		await vi.advanceTimersByTimeAsync(0);

		store.removeCondition(0);
		await vi.advanceTimersByTimeAsync(0);

		expect(vi.mocked(createRule).mock.calls.at(-1)![0].conditions).toEqual([
			{ field: 'purpose', op: 'contains', value: 'B' }
		]);
		store.removeCondition(0);
		expect(store.form.conditions).toHaveLength(1);
		expect(store.form.conditions[0].value).toBe('');
		expect(store.previewStatus).toBe('idle');
	});

	it('shows a refused row at the editor row it came from, blank rows left out of the request', async () => {
		vi.mocked(createRule).mockRejectedValue(
			failure(422, 'invalid_rule', [
				{
					location: ['body', 'conditions[1].value'],
					message: 'conditions[1]: the regex does not compile (at position 2)',
					type: 'invalid_rule'
				}
			])
		);
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();

		store.edit({
			target: 3,
			conditions: [cond('A'), cond(''), cond('(x', 'purpose', 'regex')]
		});
		await vi.advanceTimersByTimeAsync(DEBOUNCE);

		expect(store.fieldErrors.rows).toEqual({ 2: 'The regex does not compile (at position 2)' });
	});

	it('keeps the source columns of the held preview: the fields its conditions read', async () => {
		vi.mocked(createRule).mockResolvedValue(out());
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();

		store.edit({ target: 3, conditions: [cond('x', 'purpose', 'contains')] }, true);
		await vi.advanceTimersByTimeAsync(0);

		expect(store.previewedConditions).toEqual([{ field: 'purpose', op: 'contains', value: 'x' }]);
	});
});

describe('RuleEditorStore: the form', () => {
	it('drops a target of another kind when what the rule sets changes', async () => {
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();
		store.edit({ target: 3 });

		store.edit({ sets: 'payee' });

		expect(store.form.target).toBeNull();
		expect(store.form.sets).toBe('payee');
	});

	it('drops the payee condition when a rule stops being a category rule', async () => {
		const store = new RuleEditorStore({ ruleId: null });
		await store.init();
		store.editCondition(0, { field: 'payee' });
		store.editCondition(0, { value: '4' });
		store.addCondition();
		store.editCondition(1, { value: 'x' });

		store.edit({ sets: 'counter_account' });

		expect(store.form.conditions.map((c) => c.field)).toEqual(['counterparty_name']);
		expect(store.form.conditions[0].value).toBe('x');
	});

	it('names the rules that take precedence by id', async () => {
		vi.mocked(listRules).mockResolvedValue([rule({ id: 3, name: 'Wallet' })]);
		const store = new RuleEditorStore({ ruleId: null });

		await store.init();

		expect(store.ruleName(3)).toBe('Wallet');
		expect(store.ruleName(4)).toBeUndefined();
	});
});
