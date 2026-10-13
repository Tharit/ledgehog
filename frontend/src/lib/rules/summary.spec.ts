import { describe, expect, it } from 'vitest';
import { conditionParts, summarizeConditions } from './summary.js';

describe('summarizeConditions', () => {
	it('puts every condition in a phrase, joined by "and"', () => {
		const text = summarizeConditions({
			conditions: [
				{ field: 'counterparty_name', op: 'starts_with', value: 'REWE' },
				{ field: 'purpose', op: 'contains', value: 'Markt' }
			]
		});

		expect(text).toBe('Counterparty name starts with "REWE" and Purpose contains "Markt"');
	});

	it('says each operator and field its own way', () => {
		const one = (field: string, op: string, value: string) =>
			conditionParts({ conditions: [{ field, op, value }] });

		expect(one('counterparty_name', 'equals', 'Spotify')).toEqual([
			'Counterparty name is "Spotify"'
		]);
		expect(one('purpose', 'regex', 'cloud|hosting')).toEqual([
			'Purpose matches pattern "cloud|hosting"'
		]);
		expect(one('counterparty_ref', 'starts_with', 'DE89')).toEqual([
			'Counterparty IBAN or reference starts with "DE89"'
		]);
		expect(one('mandate_ref', 'equals', 'M1')).toEqual(['Mandate reference is "M1"']);
		expect(one('booking_text', 'contains', 'DIRECT')).toEqual(['Booking text contains "DIRECT"']);
	});

	it('shows a field or operator it does not know as it came', () => {
		expect(conditionParts({ conditions: [{ field: 'iban', op: 'near', value: 'x' }] })).toEqual([
			'iban near "x"'
		]);
	});

	it('names the payee condition when it can, by id when it cannot', () => {
		const fields = { conditions: [], condition_payee_id: 7 };

		expect(summarizeConditions(fields, (id) => (id === 7 ? 'REWE' : undefined))).toBe(
			'Payee is REWE'
		);
		expect(summarizeConditions(fields)).toBe('Payee is payee 7');
	});

	it('puts the payee after the text conditions', () => {
		expect(
			summarizeConditions({
				conditions: [{ field: 'purpose', op: 'contains', value: 'x' }],
				condition_payee_id: 7
			})
		).toBe('Purpose contains "x" and Payee is payee 7');
	});

	it('says so when there is nothing', () => {
		expect(summarizeConditions({})).toBe('No conditions');
		expect(summarizeConditions({ conditions: [], condition_payee_id: null })).toBe('No conditions');
	});
});
