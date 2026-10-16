import { describe, expect, it } from 'vitest';
import {
	CONDITION_FIELDS,
	ENTRY_FIELDS,
	FIELD_LABELS,
	SOURCE_FIELDS,
	conditionText,
	fieldsRead,
	keepRowsFor,
	newConditionRow,
	payeeOfRow,
	requestRows,
	rowsFromConditions,
	toConditions
} from './conditions.js';

describe('payee rows', () => {
	it('loads and sends a payee condition like any other, skipping a blank one', () => {
		const rows = rowsFromConditions([
			{ field: 'purpose', op: 'contains', value: 'x' },
			{ field: 'payee', op: 'is', value: '7' }
		]);
		rows.push(newConditionRow({ field: 'payee', op: 'is', value: '' }));

		expect(requestRows(rows)).toEqual([0, 1]);
		expect(toConditions(rows)).toEqual([
			{ field: 'purpose', op: 'contains', value: 'x' },
			{ field: 'payee', op: 'is', value: '7' }
		]);
	});

	it('reads a payee id from a row, or none', () => {
		expect(payeeOfRow({ value: '12' })).toBe(12);
		expect(payeeOfRow({ value: '' })).toBeNull();
		expect(payeeOfRow({ value: 'x' })).toBeNull();
	});

	it('drops payee rows for a rule that cannot have them, keeping one blank row', () => {
		const rows = [newConditionRow({ field: 'payee', op: 'is', value: '7' })];

		expect(keepRowsFor(rows, true)).toEqual(rows);
		const kept = keepRowsFor(rows, false);
		expect(kept).toHaveLength(1);
		expect(kept[0]).toMatchObject({ field: 'counterparty_name', value: '' });
	});

	it('says the payee by name, or deleted', () => {
		const c = { field: 'payee', op: 'is', value: '7' };

		expect(conditionText(c, () => 'REWE')).toBe('Payee is REWE');
		expect(conditionText(c, () => undefined)).toBe('Payee is deleted');
	});
});

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

describe('the document fields', () => {
	it('are fields of the entry, listed after the five of the source transaction', () => {
		expect(SOURCE_FIELDS).toEqual([
			'counterparty_name',
			'counterparty_ref',
			'purpose',
			'booking_text',
			'mandate_ref'
		]);
		expect(ENTRY_FIELDS).toEqual(['document_merchant', 'document_line']);
		expect(CONDITION_FIELDS).toEqual([...SOURCE_FIELDS, ...ENTRY_FIELDS]);
		expect(FIELD_LABELS.document_merchant).toBe('Document merchant name');
		expect(FIELD_LABELS.document_line).toBe('Document line');
	});

	it('load as text rows with the four text operators, and are read back by fieldsRead', () => {
		const conditions = [
			{ field: 'document_merchant', op: 'equals', value: 'CloudNotes' },
			{ field: 'document_line', op: 'regex', value: 'capsule|filter' }
		];

		expect(rowsFromConditions(conditions)).toMatchObject([
			{ field: 'document_merchant', op: 'equals', value: 'CloudNotes' },
			{ field: 'document_line', op: 'regex', value: 'capsule|filter' }
		]);
		expect(fieldsRead(conditions)).toEqual(['document_merchant', 'document_line']);
		expect(conditionText(conditions[0])).toBe('Document merchant name is "CloudNotes"');
	});
});
