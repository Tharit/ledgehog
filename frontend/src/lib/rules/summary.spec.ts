import { describe, expect, it } from 'vitest';
import { conditionParts, summarizeConditions } from './summary.js';

describe('summarizeConditions', () => {
	it('puts every condition in a phrase, joined by "and"', () => {
		const text = summarizeConditions({
			name_prefix: 'PAYPAL *',
			purpose_regex: 'cloud|hosting',
			counterparty_ref: ' DE89 '
		});

		expect(text).toBe(
			'reference DE89 and name starts with “PAYPAL *” and purpose matches /cloud|hosting/'
		);
	});

	it('says each kind its own way', () => {
		expect(conditionParts({ mandate_ref: 'M1' })).toEqual(['mandate M1']);
		expect(conditionParts({ name_exact: 'Spotify' })).toEqual(['name is “Spotify”']);
		expect(conditionParts({ booking_text: 'DIRECT DEBIT' })).toEqual([
			'booking text “DIRECT DEBIT”'
		]);
	});

	it('names the payee condition when it can, by id when it cannot', () => {
		const fields = { condition_payee_id: 7 };

		expect(summarizeConditions(fields, (id) => (id === 7 ? 'REWE' : undefined))).toBe(
			'payee is REWE'
		);
		expect(summarizeConditions(fields)).toBe('payee is payee 7');
	});

	it('skips blank conditions', () => {
		expect(conditionParts({ name_prefix: '  ', purpose_regex: null, mandate_ref: '' })).toEqual([]);
		expect(summarizeConditions({})).toBe('No conditions');
	});
});
