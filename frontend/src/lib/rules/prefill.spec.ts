import { describe, expect, it } from 'vitest';
import { emptyForm } from './form.js';
import {
	applySuggestion,
	formFromEntry,
	isApplied,
	newRuleUrl,
	parseFromParams,
	suggestionsFromEntry,
	type EntryFacts
} from './prefill.js';

const facts: EntryFacts = {
	id: 42,
	counterparty_name: '  PAYPAL *SEEEDDEVELO ',
	category_id: 8
};

describe('suggestionsFromEntry', () => {
	it('offers the name as a prefix and as an exact name', () => {
		expect(suggestionsFromEntry(facts)).toEqual([
			{ field: 'name_prefix', value: 'PAYPAL *SEEEDDEVELO' },
			{ field: 'name_exact', value: 'PAYPAL *SEEEDDEVELO' }
		]);
	});

	it('offers the source fields when the entry carries them', () => {
		const found = suggestionsFromEntry({
			...facts,
			counterparty_name: null,
			counterparty_ref: 'DE89370400440532013000',
			mandate_ref: 'M-77',
			booking_text: 'SEPA direct debit'
		});

		expect(found.map((s) => s.field)).toEqual(['counterparty_ref', 'mandate_ref', 'booking_text']);
	});

	it('offers nothing for an entry without text', () => {
		expect(suggestionsFromEntry({ ...facts, counterparty_name: null })).toEqual([]);
		expect(suggestionsFromEntry({ ...facts, counterparty_name: '  ' })).toEqual([]);
	});
});

describe('the starting form', () => {
	it('sets no condition: the suggestions wait to be ticked', () => {
		const form = formFromEntry(facts);

		expect(form.name_prefix).toBe('');
		expect(form.counterparty_ref).toBe('');
		expect(form.target).toBe(8);
		expect(form.sets).toBe('category');
	});
});

describe('ticking a suggestion', () => {
	const suggestion = { field: 'name_prefix', value: 'PAYPAL *' } as const;

	it('puts its value into the field, and unticking empties it', () => {
		const on = applySuggestion(emptyForm(), suggestion, true);
		expect(on.name_prefix).toBe('PAYPAL *');
		expect(isApplied(on, suggestion)).toBe(true);

		const off = applySuggestion(on, suggestion, false);
		expect(off.name_prefix).toBe('');
		expect(isApplied(off, suggestion)).toBe(false);
	});

	it('is not applied once the field holds something else', () => {
		expect(isApplied({ ...emptyForm(), name_prefix: 'PAYPAL' }, suggestion)).toBe(false);
	});
});

describe('the address of a rule from an entry', () => {
	it('carries the id and the hints that find the entry', () => {
		const url = newRuleUrl({ id: 42, booked_on: '2026-10-09', account_id: 3 });

		expect(url).toBe('/settings/rules/new?from=42&on=2026-10-09&account=3');
		expect(parseFromParams(url.split('?')[1])).toEqual({
			id: 42,
			on: '2026-10-09',
			accountId: 3
		});
	});

	it('reads a bare id, and nothing from rubbish', () => {
		expect(parseFromParams('from=7')).toEqual({ id: 7, on: undefined, accountId: undefined });
		expect(parseFromParams('')).toBeNull();
		expect(parseFromParams('from=abc')).toBeNull();
		expect(parseFromParams('from=-1')).toBeNull();
		expect(parseFromParams('from=5&on=yesterday&account=x')).toEqual({
			id: 5,
			on: undefined,
			accountId: undefined
		});
	});
});
