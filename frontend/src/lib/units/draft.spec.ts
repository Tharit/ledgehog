import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { allocationMessage, allocationText, Draft, parseAllocation } from './draft.js';
import { unit } from './fixtures.js';

const loaded = unit({
	anchor_entry_id: 1,
	entries: [
		entry({ id: 1, version: 3, unit_key: 1, source_transaction_id: 5, description: 'Weekly shop' }),
		entry({
			id: 2,
			version: 4,
			unit_key: 1,
			source_transaction_id: 5,
			amount: { amount: -1000, currency: 'EUR' }
		})
	]
});

const empty = () => Draft.of(loaded);
/** the first entry of the request */
const first = (draft: Draft) => draft.toRequest().entries![0]!;

describe('an empty draft', () => {
	it('is not dirty and asks for nothing but the versions', () => {
		const draft = empty();
		expect(draft.isDirty).toBe(false);
		expect(draft.toRequest()).toEqual({
			anchor_entry_id: 1,
			entries: [],
			removed_entry_ids: [],
			reresolve_all: false,
			versions: { 1: 3, 2: 4 }
		});
	});

	it('takes the versions of a commit from the preview when told', () => {
		expect(empty().toRequest({ 1: 9 }).versions).toEqual({ 1: 9 });
	});
});

describe('fields', () => {
	it('fixes a value: the request carries it, and the draft is dirty', () => {
		const draft = empty().setField(1, 'category', 10);
		expect(draft.isDirty).toBe(true);
		expect(draft.toRequest().entries).toEqual([{ id: 1, category: { mode: 'fixed', value: 10 } }]);
	});

	it('names the proposal the value was accepted from', () => {
		const shown = { pass: 'history', basis: { agree: 3, of: 4 } };
		const draft = empty().setField(1, 'category', 10, shown);
		expect(first(draft).category).toEqual({
			mode: 'fixed',
			value: 10,
			shown_basis: shown
		});
	});

	it('leaves a field empty when fixed to null', () => {
		expect(first(empty().setField(1, 'payee', null)).payee).toEqual({
			mode: 'fixed',
			value: null
		});
	});

	it('resets a field to the proposal: the passes decide again', () => {
		const draft = empty().setField(1, 'category', 10).resetField(1, 'category');
		expect(draft.fieldEdit(1, 'category')).toEqual({ mode: 'reresolve' });
		expect(first(draft).category).toEqual({ mode: 'reresolve' });
	});

	it('reverts an edit: untouched again, and the draft is clean', () => {
		const draft = empty().setField(1, 'category', 10).revertField(1, 'category');
		expect(draft.fieldEdit(1, 'category')).toBeUndefined();
		expect(draft.isDirty).toBe(false);
	});
});

describe('texts', () => {
	it('sends a description that differs from the stored one, trimmed; null empties it', () => {
		expect(first(empty().setDescription(1, ' Groceries ')).description).toBe('Groceries');
		const emptied = first(empty().setDescription(1, '   '));
		expect(emptied.description).toBeNull();
		expect('description' in emptied).toBe(true);
	});

	it('is not an edit when the text is the one that is stored', () => {
		expect(empty().setDescription(1, 'Weekly shop').isDirty).toBe(false);
		expect(empty().setNote(1, '').isDirty).toBe(false);
		expect(empty().setNote(1, null).isDirty).toBe(false);
	});

	it('keeps a space typed at the end: the edit stays until the text is the stored one again', () => {
		const typing = empty().setDescription(1, 'Weekly shop ');
		expect(typing.edit(1).description).toBe('Weekly shop ');
		expect(typing.toRequest().entries![0]!.description).toBe('Weekly shop');
		expect(typing.setDescription(1, 'Weekly shop').isDirty).toBe(false);
	});

	it('keeps the raw text while it is typed', () => {
		expect(empty().setNote(1, 'a ').edit(1).note).toBe('a ');
	});
});

describe('splits', () => {
	it('adds a row with a temporary negative id; without an amount it is pending and not sent', () => {
		const draft = empty().addSplit(1);
		expect(draft.splits).toEqual([{ id: -1, sourceEntryId: 1 }]);
		expect(draft.pendingSplits).toHaveLength(1);
		expect(draft.isDirty).toBe(true);
		expect(draft.toRequest().entries).toEqual([]);
	});

	it('numbers the next temporary id below the last', () => {
		expect(
			empty()
				.addSplit(1)
				.addSplit(1)
				.splits.map((s) => s.id)
		).toEqual([-1, -2]);
	});

	it('sends a split with its amount, its source entry and its fields', () => {
		const draft = empty().addSplit(1).setSplitAmount(-1, -1500).setField(-1, 'category', 11);
		expect(draft.pendingSplits).toHaveLength(0);
		expect(draft.toRequest().entries).toEqual([
			{
				id: -1,
				source_entry_id: 1,
				amount: -1500,
				category: { mode: 'fixed', value: 11 }
			}
		]);
	});

	it('reallocates a stored entry of a split; an amount equal to the stored one is no edit', () => {
		const changed = empty().setSplitAmount(2, -2000);
		expect(changed.toRequest().entries).toEqual([{ id: 2, amount: -2000 }]);
		expect(changed.setSplitAmount(2, -1000).isDirty).toBe(false);
	});

	it('removes a new row outright and a stored one by listing it as removed', () => {
		const added = empty().addSplit(1).setSplitAmount(-1, -5);
		expect(added.removeSplit(-1).isDirty).toBe(false);
		const removed = empty().setSplitAmount(2, -3).removeSplit(2);
		expect(removed.removed).toEqual([2]);
		expect(removed.toRequest().removed_entry_ids).toEqual([2]);
		expect(removed.toRequest().entries).toEqual([]);
		expect(removed.restoreSplit(2).isDirty).toBe(false);
	});

	it('never removes the anchor', () => {
		expect(empty().removeSplit(1).removed).toEqual([]);
	});
});

describe('type', () => {
	it('converts to a transfer with its counter-account and drops the flow fields', () => {
		const draft = empty().setField(1, 'category', 10).convertToTransfer(1, 7);
		const body = first(draft);
		expect(body.type).toEqual({ mode: 'fixed', value: 'transfer' });
		expect(body.counter_account).toEqual({ mode: 'fixed', value: 7 });
		expect(body.category).toBeUndefined();
	});

	it('converts to a transfer whose destination is still to be chosen', () => {
		const body = first(empty().convertToTransfer(1, null));
		expect(body.type).toEqual({ mode: 'fixed', value: 'transfer' });
		expect(body.counter_account).toBeUndefined();
	});

	it('converts back to a flow, dropping the destination', () => {
		const body = first(empty().convertToTransfer(1, 7).convertToFlow(1));
		expect(body.type).toEqual({ mode: 'fixed', value: 'flow' });
		expect(body.counter_account).toBeUndefined();
	});
});

describe('re-resolve and stale picks', () => {
	it('re-resolves the whole unit, and can undo it', () => {
		const draft = empty().reresolve();
		expect(draft.isDirty).toBe(true);
		expect(draft.toRequest().reresolve_all).toBe(true);
		expect(draft.reresolve(false).isDirty).toBe(false);
	});

	it('forgets a pick whose category vanished, and only that pick', () => {
		const draft = empty()
			.setField(1, 'category', 10)
			.setField(2, 'category', 11)
			.setField(1, 'payee', 20)
			.dropReference('category', 10);
		expect(draft.fieldEdit(1, 'category')).toBeUndefined();
		expect(draft.fieldEdit(2, 'category')).toEqual({ mode: 'fixed', value: 11, shown: null });
		expect(draft.fieldEdit(1, 'payee')).toBeDefined();
	});
});

describe('rebase', () => {
	it('keeps what still applies over the unit as it is now, with its versions', () => {
		const draft = empty().setField(1, 'category', 10).setField(2, 'category', 11).addSplit(2);
		const now = unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, version: 8, unit_key: 1, source_transaction_id: 5 })]
		});

		const next = draft.rebase(now);

		expect(next.versions).toEqual({ 1: 8 });
		expect(next.fieldEdit(1, 'category')).toBeDefined();
		expect(next.fieldEdit(2, 'category')).toBeUndefined();
		expect(next.splits).toEqual([]); // its source entry left
	});

	it('drops a text edit that now equals what is stored', () => {
		const draft = empty().setNote(1, 'moved');
		const now = unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, version: 5, unit_key: 1, note: 'moved' })]
		});
		expect(draft.rebase(now).isDirty).toBe(false);
	});

	it('moves the anchor when the anchor entry is gone', () => {
		const now = unit({ anchor_entry_id: 2, entries: [entry({ id: 2, unit_key: 2 })] });
		expect(empty().rebase(now).anchorId).toBe(2);
	});
});

describe('allocations', () => {
	it('takes the sign of the entry it splits', () => {
		expect(parseAllocation('12,50', 'EUR', 'de', -4731)).toEqual({ ok: true, minor: -1250 });
		expect(parseAllocation('12.50', 'EUR', 'en', 4731)).toEqual({ ok: true, minor: 1250 });
		expect(parseAllocation('-12.50', 'EUR', 'en', -4731)).toEqual({ ok: true, minor: -1250 });
	});

	it('refuses zero, nothing and what is ambiguous, with words', () => {
		expect(parseAllocation('0', 'EUR', 'en', -1)).toEqual({ ok: false, error: 'zero' });
		expect(parseAllocation('', 'EUR', 'en', -1)).toEqual({ ok: false, error: 'empty' });
		expect(parseAllocation('1,234', 'EUR', 'en', -1)).toEqual({ ok: false, error: 'ambiguous' });
		expect(allocationMessage('invalid')).toMatch(/not an amount/);
	});

	it('writes the amount as typed: its magnitude in the locale', () => {
		expect(allocationText(-1250, 'EUR', 'de')).toBe('12,50');
		expect(allocationText(-1250, 'EUR', 'en')).toBe('12.50');
	});
});
