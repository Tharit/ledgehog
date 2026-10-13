import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { source } from './fixtures.js';
import { parseExampleId, sourceRows, withExample } from './example.js';

describe('the example in the address', () => {
	it('reads the entry id', () => {
		expect(parseExampleId('?from=42')).toBe(42);
		expect(parseExampleId('?x=1&from=7')).toBe(7);
	});

	it('is null for anything that is not an id', () => {
		expect(parseExampleId('')).toBeNull();
		expect(parseExampleId('?from=')).toBeNull();
		expect(parseExampleId('?from=abc')).toBeNull();
		expect(parseExampleId('?from=-3')).toBeNull();
		expect(parseExampleId('?from=1.5')).toBeNull();
		expect(parseExampleId('?from=0')).toBeNull();
	});

	it('sets, changes and removes it, keeping the rest of the address', () => {
		expect(withExample('/settings/rules/new', 5)).toBe('/settings/rules/new?from=5');
		expect(withExample('/settings/rules/new?from=5', 9)).toBe('/settings/rules/new?from=9');
		expect(withExample('/settings/rules/new?from=5', null)).toBe('/settings/rules/new');
		expect(withExample('/settings/rules/3?x=1#top', 8)).toBe('/settings/rules/3?x=1&from=8#top');
		expect(withExample(new URL('http://h/settings/rules/new?from=1'), null)).toBe(
			'/settings/rules/new'
		);
	});
});

describe('sourceRows', () => {
	it('lists the five fields a rule reads, in the editor order, with their plain labels', () => {
		const rows = sourceRows(
			entry({ source: source({ counterparty_name: 'REWE', purpose: 'Einkauf Markt' }) })
		);

		expect(rows?.map((r) => r.label)).toEqual([
			'Counterparty name',
			'Counterparty IBAN or reference',
			'Purpose',
			'Booking text',
			'Mandate reference'
		]);
		expect(rows?.find((r) => r.field === 'purpose')?.value).toBe('Einkauf Markt');
	});

	it('has no value for a field the source lacks, blank included', () => {
		const rows = sourceRows(entry({ source: source({ booking_text: null, mandate_ref: '' }) }));

		expect(rows?.find((r) => r.field === 'booking_text')?.value).toBeNull();
		expect(rows?.find((r) => r.field === 'mandate_ref')?.value).toBeNull();
	});

	it('is null for an entry without a source transaction', () => {
		expect(sourceRows(entry({ source: null }))).toBeNull();
	});
});
