import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import {
	allocationMessage,
	allocationText,
	Draft,
	parseAllocation,
	parseReceivedAmount
} from './draft.js';
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
		const decided = Draft.of(
			unit({ anchor_entry_id: 1, entries: [entry({ id: 1, unit_key: 1, payee_id: 20 })] })
		);
		expect(first(decided.setField(1, 'payee', null)).payee).toEqual({
			mode: 'fixed',
			value: null
		});
	});

	it('is no edit to choose the value that is stored; back to it undoes the edit', () => {
		const decided = Draft.of(
			unit({
				anchor_entry_id: 1,
				entries: [entry({ id: 1, unit_key: 1, category_id: 10, payee_id: 20, type: 'flow' })]
			})
		);
		expect(decided.setField(1, 'category', 10).isDirty).toBe(false);
		expect(decided.setField(1, 'payee', 20).isDirty).toBe(false);
		expect(decided.setField(1, 'type', 'flow').isDirty).toBe(false);
		expect(decided.setField(1, 'category', 11).setField(1, 'category', 10).isDirty).toBe(false);
	});

	it('is an edit to choose the stored value of a proposal the user was shown: it confirms it', () => {
		const shown = { pass: 'history', basis: { agree: 3, of: 4 } };
		const proposed = Draft.of(
			unit({ anchor_entry_id: 1, entries: [entry({ id: 1, unit_key: 1, category_id: 10 })] })
		);
		expect(proposed.setField(1, 'category', 10, shown).isDirty).toBe(true);
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
		expect(draft.splits).toEqual([{ id: -1, sourceEntryId: 1, tags: [] }]);
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
		const pair = Draft.of(
			unit({
				anchor_entry_id: 1,
				entries: [entry({ id: 1, unit_key: 1, type: 'transfer', counter_account_id: 7 })]
			})
		);
		const body = first(pair.convertToFlow(1));
		expect(body.type).toEqual({ mode: 'fixed', value: 'flow' });
		expect(body.counter_account).toBeUndefined();
	});

	it('is no edit to convert to the type the entry has; converting and back is clean', () => {
		expect(empty().convertToFlow(1).isDirty).toBe(false);
		expect(empty().convertToTransfer(1, null).convertToFlow(1).isDirty).toBe(false);
	});

	it('converts an entry with no type yet to a flow when asked', () => {
		const open = Draft.of(
			unit({ anchor_entry_id: 1, entries: [entry({ id: 1, unit_key: 1, type: null })] })
		);
		expect(first(open.convertToFlow(1)).type).toEqual({ mode: 'fixed', value: 'flow' });
		expect(first(open.convertToTransfer(1, null)).type).toEqual({
			mode: 'fixed',
			value: 'transfer'
		});
	});
});

describe('re-resolve and stale picks', () => {
	it('re-resolves the whole unit, and can undo it', () => {
		const draft = empty().reresolve();
		expect(draft.isDirty).toBe(true);
		expect(draft.toRequest().reresolve_all).toBe(true);
		expect(draft.reresolve(false).isDirty).toBe(false);
	});

	it('re-resolves pending changes too: the derived values the user chose are dropped', () => {
		const draft = empty()
			.setField(1, 'category', 10)
			.setField(1, 'payee', 20)
			.convertToTransfer(2, 7)
			.resetField(2, 'payee')
			.reresolve();
		expect(draft.reresolveAll).toBe(true);
		expect(draft.fieldEdit(1, 'category')).toBeUndefined();
		expect(draft.fieldEdit(2, 'type')).toBeUndefined();
		expect(draft.fieldEdit(2, 'payee')).toBeUndefined();
		expect(draft.toRequest().entries).toEqual([]);
	});

	it('re-resolve keeps splits, their amounts and fields, removals, descriptions and notes', () => {
		const draft = empty()
			.addSplit(1)
			.setSplitAmount(-1, -500)
			.setField(-1, 'category', 11)
			.removeSplit(2)
			.setDescription(1, 'mine')
			.setNote(1, 'a note')
			.setField(1, 'category', 10)
			.reresolve();
		expect(draft.splits).toEqual([{ id: -1, sourceEntryId: 1, tags: [] }]);
		expect(draft.removed).toEqual([2]);
		expect(draft.toRequest().entries).toEqual([
			{ id: 1, description: 'mine', note: 'a note' },
			{ id: -1, source_entry_id: 1, amount: -500 }
		]);
	});

	it('re-resolving again changes nothing once nothing is left to drop', () => {
		const once = empty().reresolve();
		expect(once.reresolve()).toBe(once);
		expect(once.setField(1, 'category', 10).reresolve().fieldEdit(1, 'category')).toBeUndefined();
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

	it('drops a field edit that now equals what is stored', () => {
		const draft = empty().setField(1, 'category', 10);
		const now = unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, version: 5, unit_key: 1, category_id: 10 })]
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

describe('clearField (the X)', () => {
	const flowEntry = (over: Parameters<typeof entry>[0] = {}) =>
		Draft.of(unit({ anchor_entry_id: 1, entries: [entry({ id: 1, unit_key: 1, ...over })] }));

	it('is the user’s "no payee" decision on a payee: fixed null, a standing value', () => {
		const draft = flowEntry({ payee_id: 20 }).clearField(1, 'payee');
		expect(draft.fieldEdit(1, 'payee')).toEqual({ mode: 'fixed', value: null, shown: null });
		expect(first(draft).payee).toEqual({ mode: 'fixed', value: null });
	});

	it('is still a decision over an undecided empty payee (stored null with no key)', () => {
		const draft = flowEntry({ payee_id: null }).clearField(1, 'payee');
		expect(first(draft).payee).toEqual({ mode: 'fixed', value: null });
		expect(draft.isDirty).toBe(true);
	});

	it('is no edit over a stored "no payee" decision, and drops an edit made over it', () => {
		const decided = flowEntry({ payee_id: null, derivation: { payee: { pass: 'user' } } });
		expect(decided.clearField(1, 'payee').isDirty).toBe(false);
		expect(decided.setField(1, 'payee', 20).clearField(1, 'payee').isDirty).toBe(false);
	});

	it('asks the passes again for type, category and counter account, never fixed null', () => {
		for (const field of ['type', 'category', 'counter_account'] as const) {
			const draft = flowEntry({ category_id: 10 }).setField(1, field, null).clearField(1, field);
			expect(draft.fieldEdit(1, field)).toEqual({ mode: 'reresolve' });
			expect(first(draft)[field]).toEqual({ mode: 'reresolve' });
		}
	});

	it('replaces a value the user picked in the draft', () => {
		const draft = flowEntry({ category_id: 10 })
			.setField(1, 'category', 11)
			.clearField(1, 'category');
		expect(draft.fieldEdit(1, 'category')).toEqual({ mode: 'reresolve' });
	});

	it('keeps a fixed null over an undecided payee through a rebase, and drops the stored decision', () => {
		const open = unit({ anchor_entry_id: 1, entries: [entry({ id: 1, unit_key: 1 })] });
		const draft = Draft.of(open).clearField(1, 'payee');
		expect(draft.rebase(open).fieldEdit(1, 'payee')).toBeDefined();
		const decided = unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, unit_key: 1, derivation: { payee: { pass: 'user' } } })]
		});
		expect(draft.rebase(decided).fieldEdit(1, 'payee')).toBeUndefined();
	});

	it('lists its field edits and tells other changes apart', () => {
		const draft = flowEntry({ category_id: 10 }).clearField(1, 'category');
		expect(draft.fieldEdits()).toEqual([{ id: 1, field: 'category', edit: { mode: 'reresolve' } }]);
		expect(draft.hasOtherChanges).toBe(false);
		expect(draft.setNote(1, 'x').hasOtherChanges).toBe(true);
		expect(draft.reresolve().hasOtherChanges).toBe(true);
	});
});

describe('tags', () => {
	const tagged = unit({
		anchor_entry_id: 1,
		entries: [
			entry({ id: 1, version: 3, unit_key: 1, source_transaction_id: 5, tag_ids: [30, 31] }),
			entry({
				id: 2,
				version: 4,
				unit_key: 1,
				source_transaction_id: 5,
				amount: { amount: -1000, currency: 'EUR' },
				tag_ids: [32]
			})
		]
	});
	const base = () => Draft.of(tagged);

	it('starts untouched: the stored tags, no edit, no tags in the request', () => {
		const draft = base();
		expect(draft.effectiveTagIds(1)).toEqual([30, 31]);
		expect(draft.tagEdit(1)).toBeUndefined();
		expect(draft.isDirty).toBe(false);
		expect(draft.toRequest().entries).toEqual([]);
	});

	it('toggling a stored tag off removes it; toggling it back leaves no edit', () => {
		const off = base().toggleTag(1, 30);
		expect(off.tagEdit(1)).toEqual({ add: [], remove: [30] });
		expect(off.effectiveTagIds(1)).toEqual([31]);
		const back = off.toggleTag(1, 30);
		expect(back.tagEdit(1)).toBeUndefined();
		expect(back.isDirty).toBe(false);
		expect(back.effectiveTagIds(1)).toEqual([30, 31]);
	});

	it('toggling a tag the entry does not have adds it; toggling it back leaves no edit', () => {
		const on = base().toggleTag(1, 99);
		expect(on.tagEdit(1)).toEqual({ add: [99], remove: [] });
		expect(on.effectiveTagIds(1)).toEqual([30, 31, 99]);
		expect(on.toggleTag(1, 99).tagEdit(1)).toBeUndefined();
	});

	it('keeps the change relative to the stored tags, add and remove side by side', () => {
		const draft = base().toggleTag(1, 31).toggleTag(1, 98).toggleTag(1, 97);
		expect(draft.tagEdit(1)).toEqual({ add: [97, 98], remove: [31] });
		expect(first(draft)).toEqual({ id: 1, tags: { add: [97, 98], remove: [31] } });
	});

	it('is a change of its own: dirty, an other change, and committable on its own', () => {
		const draft = base().toggleTag(1, 30);
		expect(draft.isDirty).toBe(true);
		expect(draft.hasOtherChanges).toBe(true);
		expect(draft.fieldEdits()).toEqual([]);
	});

	it('leaves tags out of the request of an entry that has no tag change', () => {
		const body = first(base().setNote(1, 'x'));
		expect(body).not.toHaveProperty('tags');
	});

	it('starts a new split row with the tags of the original, the change on top', () => {
		const draft = base().addSplit(1);
		expect(draft.splits).toEqual([{ id: -1, sourceEntryId: 1, tags: [30, 31] }]);
		expect(draft.effectiveTagIds(-1)).toEqual([30, 31]);
		const off = draft.toggleTag(-1, 30).toggleTag(-1, 99).setSplitAmount(-1, -500);
		expect(off.effectiveTagIds(-1)).toEqual([31, 99]);
		expect(off.toRequest().entries).toEqual([
			{ id: -1, source_entry_id: 1, amount: -500, tags: { add: [99], remove: [30] } }
		]);
		// toggling an inherited tag off and on again is no edit
		expect(draft.toggleTag(-1, 30).toggleTag(-1, 30).tagEdit(-1)).toBeUndefined();
	});

	it('leaves the original’s tags alone when only the split row changes them', () => {
		const draft = base().addSplit(1).toggleTag(-1, 30);
		expect(draft.effectiveTagIds(1)).toEqual([30, 31]);
	});

	it('survives a re-resolve, which never touches tags', () => {
		const draft = base().toggleTag(1, 30).setField(1, 'category', 10).reresolve();
		expect(draft.tagEdit(1)).toEqual({ add: [], remove: [30] });
		expect(draft.fieldEdit(1, 'category')).toBeUndefined();
	});

	it('rebases over the reloaded tags: an edit that became a no-op is dropped', () => {
		const draft = base().toggleTag(1, 30).toggleTag(1, 99).toggleTag(2, 32);
		const now = unit({
			anchor_entry_id: 1,
			entries: [
				// 30 was taken off meanwhile, 99 put on: both edits are done already
				entry({ id: 1, version: 8, unit_key: 1, source_transaction_id: 5, tag_ids: [31, 99, 40] }),
				entry({ id: 2, version: 4, unit_key: 1, source_transaction_id: 5, tag_ids: [32] })
			]
		});
		const next = draft.rebase(now);
		expect(next.tagEdit(1)).toBeUndefined();
		expect(next.tagEdit(2)).toEqual({ add: [], remove: [32] });
		// a still-needed edit stays relative to the reloaded tags
		const again = base().toggleTag(1, 31).toggleTag(1, 99).rebase(now);
		expect(again.tagEdit(1)).toEqual({ add: [], remove: [31] });
		expect(again.effectiveTagIds(1)).toEqual([99, 40]);
	});

	it('rebases a split row onto what its source stores now', () => {
		const draft = base().addSplit(1).toggleTag(-1, 30).toggleTag(-1, 99);
		const now = unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, version: 8, unit_key: 1, source_transaction_id: 5, tag_ids: [99] })]
		});
		const next = draft.rebase(now);
		expect(next.splits).toEqual([{ id: -1, sourceEntryId: 1, tags: [99] }]);
		expect(next.tagEdit(-1)).toBeUndefined(); // 30 is not inherited any more, 99 is
	});

	it('forgets a tag that no longer exists, keeping the rest of the change', () => {
		const draft = base().toggleTag(1, 30).toggleTag(1, 99).toggleTag(2, 99);
		const next = draft.dropTag(99);
		expect(next.tagEdit(1)).toEqual({ add: [], remove: [30] });
		expect(next.tagEdit(2)).toBeUndefined();
		expect(draft.dropTag(12345)).toBe(draft);
	});

	it('drops the change with the split row', () => {
		const draft = base().addSplit(1).toggleTag(-1, 99).removeSplit(-1);
		expect(draft.isDirty).toBe(false);
	});
});

describe('tags of an entry that is gone', () => {
	it('takes no change', () => {
		const draft = Draft.of(loaded);
		expect(draft.toggleTag(-4, 1)).toBe(draft);
		expect(draft.toggleTag(99, 1)).toBe(draft);
	});
});

describe('tags of a new split row follow the original as shown', () => {
	const A = 30;
	const B = 31;
	const one = unit({
		anchor_entry_id: 1,
		entries: [entry({ id: 1, version: 3, unit_key: 1, source_transaction_id: 5, tag_ids: [A] })]
	});
	const start = () => Draft.of(one);

	it('starts from the original’s draft tags and sends the difference to the stored ones', () => {
		const draft = start().toggleTag(1, A).toggleTag(1, B).addSplit(1).setSplitAmount(-1, -500);
		expect(draft.effectiveTagIds(-1)).toEqual([B]);
		const row = draft.toRequest().entries!.find((e) => e.id === -1)!;
		expect(row.tags).toEqual({ add: [B], remove: [A] });
	});

	it('takes the stored set with an empty change from an untouched original', () => {
		const draft = start().addSplit(1).setSplitAmount(-1, -500);
		expect(draft.effectiveTagIds(-1)).toEqual([A]);
		expect(draft.tagEdit(-1)).toBeUndefined();
		expect(draft.toRequest().entries![0]).not.toHaveProperty('tags');
	});

	it('is independent once added: later edits of the original do not move it', () => {
		const draft = start().addSplit(1).toggleTag(1, A).toggleTag(1, B);
		expect(draft.effectiveTagIds(1)).toEqual([B]);
		expect(draft.effectiveTagIds(-1)).toEqual([A]);
	});

	it('toggles relative to its start set', () => {
		const draft = start().toggleTag(1, A).addSplit(1); // starts as []
		expect(draft.effectiveTagIds(-1)).toEqual([]);
		const on = draft.toggleTag(-1, A);
		expect(on.effectiveTagIds(-1)).toEqual([A]);
		expect(on.tagEdit(-1)).toBeUndefined(); // back to the stored set
		expect(draft.toggleTag(-1, B).tagEdit(-1)).toEqual({ add: [B], remove: [A] });
	});

	it('keeps the row’s change relative to the reloaded stored tags through a rebase', () => {
		const draft = start().toggleTag(1, A).toggleTag(1, B).addSplit(1);
		const now = unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, version: 8, unit_key: 1, source_transaction_id: 5, tag_ids: [B] })]
		});
		const next = draft.rebase(now);
		// B is stored now: only the removal of A is moot too, so nothing is left to change
		expect(next.effectiveTagIds(-1)).toEqual([B]);
		expect(next.tagEdit(-1)).toBeUndefined();
	});

	it('removing the row takes its tags with it', () => {
		const draft = start().addSplit(1).toggleTag(-1, B).removeSplit(-1);
		expect(draft.isDirty).toBe(false);
	});
});

describe('the partner of a transfer leg', () => {
	it('a pick is a draft edit: dirty, another change than a field, and in the request of that entry only', () => {
		const draft = empty().pickPartner(1, 77);
		expect(draft.isDirty).toBe(true);
		expect(draft.hasOtherChanges).toBe(true);
		expect(draft.hasPick).toBe(true);
		expect(draft.toRequest().entries).toEqual([
			{ id: 1, pairing: { mode: 'pick', partner_entry_id: 77 } }
		]);
		// an entry with no pick says nothing about pairing
		expect(empty().setField(1, 'category', 10).toRequest().entries![0]).not.toHaveProperty(
			'pairing'
		);
	});

	it('picks again: the last pick stands', () => {
		expect(first(empty().pickPartner(1, 77).pickPartner(1, 78)).pairing).toEqual({
			mode: 'pick',
			partner_entry_id: 78
		});
	});

	it('takes the pick back (clearPairing): the draft is clean again', () => {
		const draft = empty().pickPartner(1, 77).clearPairing(1);
		expect(draft.isDirty).toBe(false);
		expect(draft.hasPick).toBe(false);
		expect(draft.toRequest().entries).toEqual([]);
	});

	it('asks to pair by the rules again (reresolvePairing), which is not a pick', () => {
		const draft = empty().reresolvePairing(1);
		expect(first(draft).pairing).toEqual({ mode: 'reresolve', partner_entry_id: null });
		expect(draft.isDirty).toBe(true);
		expect(draft.hasPick).toBe(false);
	});

	it('is for a stored entry only: a split row has no partner', () => {
		const draft = empty().addSplit(1);
		expect(draft.pickPartner(-1, 77)).toBe(draft);
	});

	it('a draft-level re-resolve drops the pick, so none outlives it', () => {
		const draft = empty().pickPartner(1, 77).reresolve();
		expect(draft.hasPick).toBe(false);
		expect(draft.toRequest()).toMatchObject({ reresolve_all: true, entries: [] });
	});

	it('the user’s own counter-account, type or a reset of them takes the pick back', () => {
		expect(empty().pickPartner(1, 77).setField(1, 'counter_account', 3).hasPick).toBe(false);
		expect(empty().pickPartner(1, 77).resetField(1, 'counter_account').hasPick).toBe(false);
		expect(empty().pickPartner(1, 77).convertToFlow(1).hasPick).toBe(false);
		// a category is no word about the pair
		expect(empty().pickPartner(1, 77).setField(1, 'category', 10).hasPick).toBe(true);
	});

	it('survives a rebase over the unit as it is now, and goes with an entry that is gone', () => {
		const draft = empty().pickPartner(1, 77);
		expect(draft.rebase(loaded).hasPick).toBe(true);
		const gone = unit({ anchor_entry_id: 2, entries: [loaded.entries[1]] });
		expect(draft.rebase(gone).hasPick).toBe(false);
	});
});

describe('the counter-leg of a transfer leg', () => {
	const picked = () => empty().pickCounterLeg(1);

	it('is a draft edit with a client-issued negative id, in the request of that entry', () => {
		const draft = picked();
		expect(draft.isDirty).toBe(true);
		expect(draft.hasOtherChanges).toBe(true);
		expect(draft.hasCounterLeg).toBe(true);
		expect(draft.hasPick).toBe(false);
		expect(draft.toRequest().entries).toEqual([
			{
				id: 1,
				pairing: { mode: 'counter_leg', counter_leg: { temp_id: -1, received_amount: null } }
			}
		]);
	});

	it('keeps its id for the draft’s life, and a split never takes it', () => {
		const draft = picked();
		expect(draft.pickCounterLeg(1).edit(1).pairing).toMatchObject({ tempId: -1 });
		const withSplit = draft.addSplit(1);
		expect(withSplit.splits[0].id).toBe(-2);
		expect(withSplit.pickCounterLeg(1).edit(1).pairing).toMatchObject({ tempId: -1 });
		// the counter-leg after a split gets the next id too
		expect(empty().addSplit(1).pickCounterLeg(1).edit(1).pairing).toMatchObject({ tempId: -2 });
	});

	it('holds the amount received, unsigned, and picking again keeps it', () => {
		const draft = picked().setReceivedAmount(1, 9000);
		expect(first(draft).pairing).toEqual({
			mode: 'counter_leg',
			counter_leg: { temp_id: -1, received_amount: 9000 }
		});
		expect(draft.pickCounterLeg(1).edit(1).pairing).toMatchObject({ receivedAmount: 9000 });
		expect(draft.pickCounterLeg(1, { receivedAmount: null }).edit(1).pairing).toMatchObject({
			receivedAmount: null
		});
		expect(picked().setReceivedAmount(1, null)).toBeTruthy();
		// no amount without a counter-leg
		const plain = empty();
		expect(plain.setReceivedAmount(1, 100)).toBe(plain);
	});

	it('is gone with Reset (a fresh draft), a re-resolve, another pick, a flow or another counter-account', () => {
		expect(picked().reresolve().toRequest()).toMatchObject({ reresolve_all: true, entries: [] });
		expect(picked().pickPartner(1, 77).hasCounterLeg).toBe(false);
		expect(picked().convertToFlow(1).hasCounterLeg).toBe(false);
		expect(picked().setField(1, 'counter_account', 3).hasCounterLeg).toBe(false);
		expect(picked().clearPairing(1).isDirty).toBe(false);
	});

	it('is for a stored entry only', () => {
		const draft = empty().addSplit(1);
		expect(draft.pickCounterLeg(-1)).toBe(draft);
	});
});

describe('parseReceivedAmount', () => {
	it('reads an unsigned amount in the currency, whatever sign is typed', () => {
		expect(parseReceivedAmount('90.00', 'USD', 'en')).toEqual({ ok: true, minor: 9000 });
		expect(parseReceivedAmount('-90.00', 'USD', 'en')).toEqual({ ok: true, minor: 9000 });
	});

	it('rejects what is ambiguous, empty or nothing, with the allocation messages', () => {
		expect(parseReceivedAmount('1,000', 'USD', 'en')).toEqual({ ok: false, error: 'ambiguous' });
		expect(parseReceivedAmount('', 'USD', 'en')).toEqual({ ok: false, error: 'empty' });
		expect(parseReceivedAmount('0', 'USD', 'en')).toEqual({ ok: false, error: 'zero' });
		expect(allocationMessage('ambiguous')).toContain('Write the decimals out');
	});
});
