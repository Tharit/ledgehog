import { describe, expect, it } from 'vitest';
import { sourceColumns, sourceText } from './preview.js';
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

describe('sourceColumns and the payee condition', () => {
	it('leaves a payee condition out: the preview rows carry only the source fields', () => {
		expect(
			sourceColumns([
				{ field: 'payee', op: 'is', value: '3' },
				{ field: 'purpose', op: 'contains', value: 'x' }
			])
		).toEqual(['counterparty_name', 'purpose']);
	});
});
