import { describe, expect, it } from 'vitest';
import {
	conditionText,
	fieldsRead,
	newConditionRow,
	requestRows,
	rowsFromConditions,
	toConditions
} from './conditions.js';

describe('rows', () => {
	it('starts with counterparty name, contains and nothing typed', () => {
		expect(newConditionRow()).toMatchObject({
			field: 'counterparty_name',
			op: 'contains',
			value: ''
		});
	});

	it('gives every row its own key', () => {
		expect(newConditionRow().key).not.toBe(newConditionRow().key);
	});

	it('makes rows of stored conditions, or one blank row when there are none', () => {
		const rows = rowsFromConditions([
			{ field: 'purpose', op: 'regex', value: 'a|b' },
			{ field: 'mandate_ref', op: 'equals', value: 'M1' }
		]);

		expect(rows.map(({ field, op, value }) => ({ field, op, value }))).toEqual([
			{ field: 'purpose', op: 'regex', value: 'a|b' },
			{ field: 'mandate_ref', op: 'equals', value: 'M1' }
		]);
		expect(rowsFromConditions([])).toHaveLength(1);
	});

	it('leaves out a stored condition on a field or operator this editor cannot show', () => {
		const rows = rowsFromConditions([{ field: 'iban', op: 'contains', value: 'x' }]);

		expect(rows).toHaveLength(1);
		expect(rows[0].value).toBe('');
	});
});

describe('the request', () => {
	it('carries the rows that have a value, trimmed, and says which they were', () => {
		const rows = [
			newConditionRow({ value: '  ' }),
			newConditionRow({ field: 'purpose', op: 'regex', value: ' x+ ' }),
			newConditionRow({ value: '' }),
			newConditionRow({ field: 'booking_text', op: 'equals', value: 'SEPA' })
		];

		expect(requestRows(rows)).toEqual([1, 3]);
		expect(toConditions(rows)).toEqual([
			{ field: 'purpose', op: 'regex', value: 'x+' },
			{ field: 'booking_text', op: 'equals', value: 'SEPA' }
		]);
	});
});

describe('fieldsRead', () => {
	it('lists each field once, in the editor order', () => {
		expect(
			fieldsRead([
				{ field: 'purpose', op: 'contains', value: 'a' },
				{ field: 'counterparty_ref', op: 'contains', value: 'b' },
				{ field: 'purpose', op: 'contains', value: 'c' }
			])
		).toEqual(['counterparty_ref', 'purpose']);
		expect(fieldsRead([])).toEqual([]);
	});
});

describe('conditionText', () => {
	it('reads as a phrase', () => {
		expect(conditionText({ field: 'counterparty_name', op: 'equals', value: 'REWE' })).toBe(
			'Counterparty name is "REWE"'
		);
	});
});
