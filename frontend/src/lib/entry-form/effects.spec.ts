import { describe, expect, it } from 'vitest';
import type { SourceDeleteCounts, SourceEditEffects } from '#lib/api/types.js';
import { describeEntry, EDIT_WARNING, summarizeDelete, summarizeEdit } from './effects.js';

const none: SourceEditEffects = {
	collapsed_entry_ids: [],
	unpaired_entry_ids: [],
	deleted_entry_ids: [],
	rederived_entry_ids: [],
	returned_to_review_ids: [],
	versions: []
};

const counts = (over: Partial<SourceDeleteCounts> = {}): SourceDeleteCounts => ({
	entries: 1,
	confirmed_entries: 0,
	tagged_entries: 0,
	tag_memberships: 0,
	partners_returning_to_review: 0,
	freed_documents: 0,
	...over
});

describe('EDIT_WARNING', () => {
	it('is the §5.6 sentence', () => {
		expect(EDIT_WARNING).toBe(
			"Entries that cannot absorb the change are collapsed into one, a pair whose amounts no longer match is broken, and the entries' values are derived again."
		);
	});
});

describe('summarizeEdit', () => {
	it('says nothing when the dry run reports nothing', () => {
		expect(summarizeEdit(none)).toEqual([]);
	});

	it('has one line per effect, counted', () => {
		expect(
			summarizeEdit({
				...none,
				collapsed_entry_ids: [2, 3],
				deleted_entry_ids: [2, 3],
				unpaired_entry_ids: [9],
				rederived_entry_ids: [1, 4, 9],
				returned_to_review_ids: [1]
			})
		).toEqual([
			'2 split entries are collapsed into the original.',
			'1 entry loses its counterpart; the transfer pair is broken.',
			'Values are derived again for 3 entries.',
			'1 entry returns to review.'
		]);
	});

	it('uses the singular for one split entry and the plural for unpaired entries', () => {
		const lines = summarizeEdit({ ...none, collapsed_entry_ids: [2], unpaired_entry_ids: [1, 2] });
		expect(lines[0]).toBe('1 split entry is collapsed into the original.');
		expect(lines[1]).toBe('2 entries lose their counterpart; the transfer pair is broken.');
	});
});

describe('summarizeDelete', () => {
	it('names entries, tags and partners in one sentence', () => {
		expect(
			summarizeDelete(
				counts({ confirmed_entries: 1, tag_memberships: 2, partners_returning_to_review: 1 })
			)
		).toBe('Removes 1 entry (confirmed), 2 tags, and sends 1 partner back to review.');
	});

	it('is short when there is little to say', () => {
		expect(summarizeDelete(counts())).toBe('Removes 1 entry.');
		expect(summarizeDelete(counts({ partners_returning_to_review: 2 }))).toBe(
			'Removes 1 entry and sends 2 partners back to review.'
		);
	});

	it('counts confirmed entries of a split and frees documents', () => {
		expect(
			summarizeDelete(
				counts({ entries: 3, confirmed_entries: 2, tag_memberships: 1, freed_documents: 1 })
			)
		).toBe('Removes 3 entries (2 confirmed), 1 tag, and frees 1 document.');
	});

	it('says all confirmed when all are', () => {
		expect(summarizeDelete(counts({ entries: 2, confirmed_entries: 2 }))).toBe(
			'Removes 2 entries (confirmed).'
		);
	});
});

describe('describeEntry', () => {
	it('is the amount with its currency and the text', () => {
		const entry = { amount: { amount: -1250, currency: 'EUR' }, display_text: 'groceries' };
		expect(describeEntry(entry, 'en')).toBe('−1250'.length > 0 ? describeEntry(entry, 'en') : '');
		expect(describeEntry(entry, 'en')).toMatch(/12\.50.*EUR · groceries$/);
		expect(describeEntry({ ...entry, display_text: null }, 'en')).toMatch(/EUR$/);
	});
});
