import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { source } from './fixtures.js';
import { entryRows, parseExampleId, sourceRows, withExample } from './example.js';

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

describe('entryRows', () => {
	const doc = (over = {}) => ({
		id: 7,
		provider: 'amazon',
		merchant_name: 'CloudNotes',
		line_count: 1,
		...over
	});
	const byField = (rows: ReturnType<typeof entryRows>, field: string) =>
		rows.find((r) => r.field === field)!;

	it('lists the payee, the document merchant name and the document line, in that order', () => {
		const rows = entryRows(entry());

		expect(rows.map((r) => [r.field, r.label])).toEqual([
			['payee', 'Payee'],
			['document_merchant', 'Document merchant name'],
			['document_line', 'Document line']
		]);
	});

	it('shows the payee by name through the lookup, a dash (no value) without one', () => {
		const named = entryRows(entry({ payee_id: 4 }), () => 'REWE');
		const none = entryRows(entry());

		expect(byField(named, 'payee').value).toBe('REWE');
		expect(byField(none, 'payee')).toMatchObject({ value: null, absent: null });
	});

	it('says there is no document linked on both document rows', () => {
		const rows = entryRows(entry({ document: null, document_line: null }));

		expect(byField(rows, 'document_merchant')).toMatchObject({
			value: null,
			absent: 'no document linked'
		});
		expect(byField(rows, 'document_line')).toMatchObject({
			value: null,
			absent: 'no document linked'
		});
	});

	it('reads the merchant name and the entry’s own line from the document', () => {
		const rows = entryRows(
			entry({
				document: doc(),
				document_line: { line_no: 1, description: 'Coffee capsules' }
			})
		);

		expect(byField(rows, 'document_merchant').value).toBe('CloudNotes');
		expect(byField(rows, 'document_line').value).toBe('Coffee capsules');
	});

	it('has no merchant value, and no reason, for a document without a merchant name', () => {
		const rows = entryRows(entry({ document: doc({ merchant_name: null }) }));

		expect(byField(rows, 'document_merchant')).toMatchObject({ value: null, absent: null });
	});

	it('says why a document of several lines gives this entry no line', () => {
		const rows = entryRows(entry({ document: doc({ line_count: 3 }), document_line: null }));

		expect(byField(rows, 'document_line').absent).toBe('the document has 3 lines, not split');
	});

	it('says only "no line" for a document of one line without one', () => {
		const rows = entryRows(entry({ document: doc({ line_count: 1 }), document_line: null }));

		expect(byField(rows, 'document_line').absent).toBe('no line');
	});
});
