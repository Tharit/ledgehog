import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { Draft } from './draft.js';
import { unit } from './fixtures.js';

const single = unit({
	anchor_entry_id: 1,
	entries: [
		entry({
			id: 1,
			version: 3,
			unit_key: 1,
			source_transaction_id: 5,
			amount: { amount: -4731, currency: 'EUR' }
		})
	]
});
// a stored split, opened on the entry that is not the original
const stored = unit({
	anchor_entry_id: 2,
	entries: [
		entry({ id: 1, version: 3, unit_key: 1, source_transaction_id: 5 }),
		entry({
			id: 2,
			version: 4,
			unit_key: 1,
			source_transaction_id: 5,
			amount: { amount: -1000, currency: 'EUR' }
		})
	]
});

const empty = () => Draft.of(single);
const row = (id: number, lineNo: number, amount: number) => ({
	id,
	sourceEntryId: 1,
	amount,
	documentLine: { documentId: 7, lineNo }
});
const proposal = () => [row(-900, 2, -3231), row(-901, 3, -500)];
const original = (draft: Draft) => draft.toRequest().entries!.find((e) => e.id === 1);

describe('the document of a draft', () => {
	it('is keep by default: no document key is sent', () => {
		expect(original(empty())).toBeUndefined();
		expect(empty().isDirty).toBe(false);
	});

	it('sends a pick with the id and the version the user saw', () => {
		const draft = empty().pickDocument(1, 7, 2);
		expect(original(draft)!.document).toEqual({
			mode: 'pick',
			document_id: 7,
			document_version: 2,
			decline_split: false
		});
		expect(draft.documentEdit(1)).toEqual({ mode: 'pick', documentId: 7, version: 2 });
		expect(draft.isDirty).toBe(true);
	});

	it('sends none and re-resolve with neither id nor version', () => {
		expect(original(empty().noDocument(1))!.document).toEqual({
			mode: 'none',
			decline_split: false
		});
		expect(original(empty().reresolveDocument(1))!.document).toEqual({
			mode: 'reresolve',
			decline_split: false
		});
	});

	it('a later decision replaces an earlier one', () => {
		const draft = empty().pickDocument(1, 7, 2).noDocument(1);
		expect(original(draft)!.document).toMatchObject({ mode: 'none' });
		expect(original(draft)!.document).not.toHaveProperty('document_id');
	});

	it('takes no document for an entry that is not stored, or not in the unit', () => {
		const draft = empty().addSplit(1);
		const id = draft.splits[0]!.id;
		expect(draft.pickDocument(id, 7, 2)).toBe(draft);
		const request = draft.setSplitAmount(id, -500).toRequest();
		expect(request.entries!.find((e) => e.id === id)).not.toHaveProperty('document');
	});

	it('is dropped, with the pick, when the document is gone', () => {
		const draft = empty().pickDocument(1, 7, 2).dropDocument(7);
		expect(draft.documentEdit(1)).toBeUndefined();
		expect(draft.isDirty).toBe(false);
		// a pick of another document stays
		expect(empty().pickDocument(1, 8, 1).dropDocument(7).documentEdit(1)).toBeDefined();
		// no id: any pick goes
		expect(empty().pickDocument(1, 8, 1).dropDocument().documentEdit(1)).toBeUndefined();
	});

	it('resets to the proposal: no decision, no refusal', () => {
		const draft = empty().noDocument(1).declineSplit(1).resetDocument(1);
		expect(draft.documentEdit(1)).toBeUndefined();
		expect(draft.declinesSplit(1)).toBe(false);
		expect(original(draft)).toBeUndefined();
	});
});

describe('splitting along the lines', () => {
	it('is anchored on the original entry, which the split never deletes', () => {
		const draft = Draft.of(stored).splitAlongLines(1, 7, 2);
		const request = draft.toRequest();
		expect(request.anchor_entry_id).toBe(1);
		expect(request.entries!.find((e) => e.id === 1)!.document).toEqual({
			mode: 'split_along_lines',
			document_id: 7,
			document_version: 2,
			decline_split: false
		});
	});

	it('keeps the anchor of any other draft', () => {
		expect(Draft.of(stored).pickDocument(1, 7, 2).toRequest().anchor_entry_id).toBe(2);
	});

	it('drops the user’s own rows and removals of the transaction', () => {
		const draft = Draft.of({ ...stored, anchor_entry_id: 1 })
			.addSplit(1)
			.removeSplit(2)
			.splitAlongLines(1, 7, 2);
		expect(draft.splits).toEqual([]);
		expect(draft.removed).toEqual([]);
	});

	it('is refused by "keep one entry", which goes back to the plain pick', () => {
		const draft = empty().splitAlongLines(1, 7, 2).declineSplit(1);
		expect(original(draft)!.document).toEqual({
			mode: 'pick',
			document_id: 7,
			document_version: 2,
			decline_split: true
		});
	});

	it('refuses the proposed split of a linked document with a keep and decline_split', () => {
		const draft = empty().declineSplit(1);
		expect(original(draft)!.document).toEqual({ mode: 'keep', decline_split: true });
		expect(draft.declinesSplit(1)).toBe(true);
	});

	it('a new decision lifts the refusal', () => {
		expect(empty().declineSplit(1).pickDocument(1, 7, 2).declinesSplit(1)).toBe(false);
	});
});

describe('the rows made from a line', () => {
	it('are taken over from the preview and echoed whole: id, source, amount and line', () => {
		const draft = empty().syncLineRows(proposal());
		const request = draft.toRequest();

		expect(request.entries).toEqual([
			{
				id: -900,
				source_entry_id: 1,
				amount: -3231,
				document_line: { document_id: 7, line_no: 2 }
			},
			{
				id: -901,
				source_entry_id: 1,
				amount: -500,
				document_line: { document_id: 7, line_no: 3 }
			}
		]);
		expect(draft.lineRows).toHaveLength(2);
	});

	it('are the proposal, not an edit, until the user changes one', () => {
		const draft = empty().syncLineRows(proposal());
		expect(draft.isDirty).toBe(false);
		expect(draft.hasOtherChanges).toBe(false);
		expect(draft.lineRowsEdited).toBe(false);

		const edited = draft.setSplitAmount(-901, -600);
		expect(edited.isDirty).toBe(true);
		expect(edited.lineRowsEdited).toBe(true);
		expect(edited.toRequest().entries!.find((e) => e.id === -901)!.amount).toBe(-600);
	});

	it('an edit of a row (a tag, a note) sticks to its line', () => {
		const draft = empty().syncLineRows(proposal()).setNote(-900, 'cables').toggleTag(-900, 4);
		const sent = draft.toRequest().entries!.find((e) => e.id === -900)!;
		expect(sent).toMatchObject({
			note: 'cables',
			tags: { add: [4], remove: [] },
			document_line: { document_id: 7, line_no: 2 }
		});
		expect(draft.isDirty).toBe(true);
	});

	it('are echoed without the row the user removed: a row left out is removed', () => {
		const draft = empty().syncLineRows(proposal()).removeSplit(-901);
		expect(draft.toRequest().entries!.map((e) => e.id)).toEqual([-900]);
		expect(draft.isDirty).toBe(true);
		// the document stays as it was
		expect(original(draft)).toBeUndefined();
	});

	it('removing the last row refuses the split, or the server would propose it again', () => {
		const draft = empty().syncLineRows(proposal()).removeSplit(-900).removeSplit(-901);
		const request = draft.toRequest();
		expect(request.entries!.map((e) => e.id)).toEqual([1]);
		expect(original(draft)!.document).toEqual({ mode: 'keep', decline_split: true });
	});

	it('go with a new decision about the document: they belong to the old one', () => {
		const draft = empty().syncLineRows(proposal());
		expect(draft.pickDocument(1, 8, 1).lineRows).toEqual([]);
		expect(draft.noDocument(1).lineRows).toEqual([]);
		expect(draft.reresolveDocument(1).lineRows).toEqual([]);
		expect(draft.declineSplit(1).lineRows).toEqual([]);
	});

	it('are taken back to the proposal by reset, keeping the decision', () => {
		const draft = empty()
			.pickDocument(1, 7, 2)
			.syncLineRows(proposal())
			.setSplitAmount(-901, -600)
			.resetSplit(1);
		expect(draft.lineRows).toEqual([]);
		expect(draft.documentEdit(1)).toEqual({ mode: 'pick', documentId: 7, version: 2 });
		expect(draft.declinesSplit(1)).toBe(false);
	});

	it('leave the draft when the preview no longer has them', () => {
		const draft = empty().syncLineRows(proposal());
		const next = draft.syncLineRows([row(-900, 2, -3231)]);
		expect(next.lineRows.map((s) => s.id)).toEqual([-900]);
		expect(next.isDirty).toBe(false);
		expect(next.syncLineRows([])).not.toBe(next);
		expect(next.syncLineRows([]).lineRows).toEqual([]);
	});

	it('change nothing when the preview says what the draft holds', () => {
		const draft = empty().syncLineRows(proposal());
		expect(draft.syncLineRows(proposal())).toBe(draft);
	});

	it('leave a temporary id free for the next split the user adds', () => {
		const draft = empty().syncLineRows([row(-(2 ** 51), 2, -100)]);
		expect(draft.nextTempId).toBeLessThan(-(2 ** 51));
	});

	it('survive a rebase over the unit read again', () => {
		const draft = empty().syncLineRows(proposal()).rebase(single);
		expect(draft.lineRows.map((s) => s.id)).toEqual([-900, -901]);
		expect(draft.isDirty).toBe(false);
	});
});
