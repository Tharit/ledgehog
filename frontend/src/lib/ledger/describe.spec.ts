import { describe, expect, it } from 'vitest';
import type { Account, Category, Payee, Tag } from '#lib/types/domain.js';
import { describeFilter } from './describe.js';
import { emptyFilter, type LedgerFilterState } from './filter.js';
import { buildLookups } from './lookups.js';

const lookups = buildLookups({
	accounts: [{ id: 1, name: 'Giro' } as Account, { id: 2, name: 'Visa' } as Account],
	categories: [{ id: 5, name: 'Groceries' } as Category],
	payees: [{ id: 6, name: 'REWE' } as Payee],
	tags: [{ id: 7, name: 'Lisbon trip' } as Tag, { id: 8, name: 'Tax' } as Tag]
});

function describe_(filter: Partial<LedgerFilterState>, locale = 'en') {
	return describeFilter({ ...emptyFilter(), ...filter }, { lookups, locale });
}

describe('describeFilter', () => {
	it('says nothing for an empty filter', () => {
		expect(describe_({})).toEqual([]);
	});

	it('writes an inclusive date range, or one open end', () => {
		expect(describe_({ from: '2026-10-01', to: '2026-10-11' })).toEqual([
			{ key: 'date', label: 'Oct 1 – Oct 11' }
		]);
		expect(describe_({ from: '2026-10-01' })[0].label).toBe('From Oct 1, 2026');
		expect(describe_({ to: '2026-10-11' })[0].label).toBe('Until Oct 11, 2026');
	});

	it('names one account, counts several, and survives an unknown id', () => {
		expect(describe_({ account_id: [1] })[0].label).toBe('Giro');
		expect(describe_({ account_id: [1, 2] })[0].label).toBe('2 accounts');
		expect(describe_({ account_id: [99] })[0].label).toBe('Account 99');
	});

	it('names tags, payees and categories', () => {
		expect(describe_({ tag_id: [7] })[0]).toEqual({ key: 'tag', label: 'Lisbon trip' });
		expect(describe_({ tag_id: [7, 8] })[0].label).toBe('2 tags');
		expect(describe_({ payee_id: [6] })[0]).toEqual({ key: 'payee', label: 'REWE' });
		expect(describe_({ category_id: [5] })[0]).toEqual({ key: 'category', label: 'Groceries' });
	});

	it('marks an exact category and an uncategorised one', () => {
		expect(describe_({ category_id: [5], category_descendants: false })[0].label).toBe(
			'Groceries (exact)'
		);
		expect(describe_({ uncategorised: true })[0].label).toBe('Uncategorised');
		expect(describe_({ category_id: [5], uncategorised: true })[0].label).toBe(
			'Groceries + uncategorised'
		);
	});

	it('writes an amount range as magnitudes with its currency and direction', () => {
		expect(
			describe_({ amount_min: 5000, amount_max: 20000, currency: 'EUR', direction: 'out' })[0]
		).toEqual({ key: 'amount', label: 'Out \u00b7 50.00\u2013200.00 EUR' });
		expect(describe_({ amount_min: 5000, currency: 'EUR' })[0].label).toBe('≥ 50.00 EUR');
		expect(describe_({ amount_max: 5000, currency: 'EUR' })[0].label).toBe('≤ 50.00 EUR');
		expect(describe_({ currency: 'EUR', direction: 'in' })[0].label).toBe('In · EUR');
	});

	it('names review flags and entry types', () => {
		expect(describe_({ flag: ['waiting'] })[0]).toEqual({ key: 'flag', label: 'Waiting' });
		expect(describe_({ flag: ['waiting', 'unconfirmed'] })[0].label).toBe('2 review flags');
		expect(describe_({ type: ['flow', 'transfer'] })[0].label).toBe('Type: Flow, Transfer');
	});

	it('quotes the text', () => {
		expect(describe_({ q: 'rewe' })[0]).toEqual({ key: 'text', label: '“rewe”' });
	});

	it('lists the parts in a fixed order', () => {
		const keys = describe_({ q: 'x', tag_id: [7], account_id: [1], from: '2026-10-01' }).map(
			(p) => p.key
		);
		expect(keys).toEqual(['date', 'account', 'tag', 'text']);
	});
});
