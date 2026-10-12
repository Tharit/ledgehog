import { describe, expect, it } from 'vitest';
import { entry } from './fixtures.js';
import {
	eligibleMarkedRows,
	extrasLabel,
	markedExplanation,
	partialReport,
	rowsPhrase,
	taggedNotice,
	taggedSummary
} from './tag-all.js';

describe('eligibleMarkedRows', () => {
	const marked = [
		entry({ id: 1, tag_ids: [] }),
		entry({ id: 2, tag_ids: [30] }),
		entry({ id: 3, type: 'opening' }),
		entry({ id: 4, tag_ids: [31] })
	];

	it('leaves out rows that carry the tag and derived entries', () => {
		expect(eligibleMarkedRows(marked, 30).map((e) => e.id)).toEqual([1, 4]);
	});

	it('follows the chosen tag', () => {
		expect(eligibleMarkedRows(marked, 31).map((e) => e.id)).toEqual([1, 2]);
	});

	it('is empty without marked rows', () => {
		expect(eligibleMarkedRows([], 30)).toEqual([]);
	});
});

describe('words', () => {
	it('pluralises rows', () => {
		expect(rowsPhrase(1, 'en')).toBe('1 row');
		expect(rowsPhrase(2, 'en')).toBe('2 rows');
	});

	it('explains the marked rows', () => {
		expect(markedExplanation(2, 'en')).toBe(
			'2 rows still shown were changed by you and no longer match this filter, so the filter does not include them.'
		);
		expect(markedExplanation(1, 'en')).toMatch(/^1 row still shown was changed by you/);
	});

	it('labels the checkbox', () => {
		expect(extrasLabel(2, 'en')).toBe('Also tag the 2 rows you changed that are still shown');
		expect(extrasLabel(1, 'en')).toBe('Also tag the 1 row you changed that is still shown');
	});

	it('sums up what was tagged', () => {
		expect(taggedSummary('T', 5, 0, 'en')).toBe('Tagged 5 entries with "T"');
		expect(taggedSummary('T', 1, 0, 'en')).toBe('Tagged 1 entry with "T"');
		expect(taggedSummary('T', 5, 2, 'en')).toBe('Tagged 5 entries with "T" and 2 rows you changed');
		expect(taggedSummary('T', 0, 2, 'en')).toBe('Tagged 2 rows you changed with "T"');
	});

	it('appends the stale sentence to a notice', () => {
		expect(taggedNotice('T', 1, 0, true, 'en')).toMatch(/^Tagged 1 entry with "T"\. .*stale/);
		expect(taggedNotice('T', 1, 0, false, 'en')).toBe('Tagged 1 entry with "T"');
	});

	it('reports a partial failure with distinct reasons', () => {
		expect(partialReport(1, 3, ['gone.', 'gone.', 'down.'], 'en')).toBe(
			'Tagged 1 of 3 of the rows you changed; 2 failed (gone. down.)'
		);
	});
});
