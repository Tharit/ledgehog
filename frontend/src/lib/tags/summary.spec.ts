import { describe, expect, it } from 'vitest';
import { formatDate } from '#lib/format/index.js';
import { tag } from '#lib/ledger/fixtures.js';
import { entriesLabel, indexTags, tagDeleteText, tagDeletedNotice, tagSpan } from './summary.js';

describe('tag summary', () => {
	it('counts entries with the right plural', () => {
		expect(entriesLabel(0)).toBe('0 entries');
		expect(entriesLabel(1)).toBe('1 entry');
		expect(entriesLabel(12)).toBe('12 entries');
	});

	it('says "no entries" without a span, one date for one day, a range otherwise', () => {
		expect(tagSpan({ starts_on: null, ends_on: null })).toBe('no entries');
		expect(tagSpan({ starts_on: '2026-03-03', ends_on: '2026-03-03' })).toBe(
			formatDate('2026-03-03')
		);
		expect(tagSpan({ starts_on: '2026-03-03', ends_on: '2026-03-09' })).toBe(
			`${formatDate('2026-03-03')} – ${formatDate('2026-03-09')}`
		);
	});

	it('names how many entries lose the tag, and says so when none', () => {
		expect(tagDeleteText({ name: 'Trip', entry_count: 3 })).toContain('3 entries will lose');
		expect(tagDeleteText({ name: 'Trip', entry_count: 1 })).toContain('1 entry will lose');
		expect(tagDeleteText({ name: 'Trip', entry_count: 0 })).toContain('No entry carries');
	});

	it('words the notice', () => {
		expect(tagDeletedNotice('Trip', 2)).toBe('Deleted tag “Trip” (2 entries).');
	});

	it('indexes by id', () => {
		expect(indexTags([tag({ id: 4 })]).get(4)?.id).toBe(4);
	});
});
