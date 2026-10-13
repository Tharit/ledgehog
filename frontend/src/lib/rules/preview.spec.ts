import { describe, expect, it } from 'vitest';
import { keyLabel, sourceColumns, sourceText } from './preview.js';
import { previewRow, source } from './fixtures.js';

describe('sourceColumns', () => {
	it('is the counterparty name alone when the conditions read nothing else', () => {
		expect(sourceColumns([{ field: 'counterparty_name', op: 'contains', value: 'x' }])).toEqual([
			'counterparty_name'
		]);
		expect(sourceColumns([])).toEqual(['counterparty_name']);
	});

	it('adds the other fields the conditions read, once each, in the editor order', () => {
		expect(
			sourceColumns([
				{ field: 'mandate_ref', op: 'equals', value: 'M' },
				{ field: 'purpose', op: 'contains', value: 'a' },
				{ field: 'purpose', op: 'regex', value: 'b' }
			])
		).toEqual(['counterparty_name', 'purpose', 'mandate_ref']);
	});
});

describe('sourceText', () => {
	it('reads the field of the row source', () => {
		const row = previewRow({ source: source({ purpose: 'Einkauf' }) });

		expect(sourceText(row, 'purpose')).toBe('Einkauf');
		expect(sourceText(row, 'booking_text')).toBeNull();
	});

	it('is null without a source', () => {
		expect(sourceText(previewRow({ source: null }), 'counterparty_name')).toBeNull();
	});
});

describe('keyLabel', () => {
	const names = (id: number) => (id === 3 ? 'Rent' : undefined);

	it('names a rule, or says it is gone', () => {
		expect(keyLabel({ pass: 'rule', basis: { rule_id: 3 } }, names)).toBe('rule: Rent');
		expect(keyLabel({ pass: 'rule', basis: { rule_id: 9 } }, names)).toBe('rule deleted');
		expect(keyLabel({ pass: 'rule', basis: {} }, names)).toBe('rule deleted');
	});

	it('uses the vocabulary of the ledger', () => {
		expect(keyLabel({ pass: 'history', basis: {} }, names)).toBe('history');
		expect(keyLabel({ pass: 'user' }, names)).toBe('you');
	});

	it('has nothing to say without a key', () => {
		expect(keyLabel(null, names)).toBeNull();
	});
});
