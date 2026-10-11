import { describe, expect, it } from 'vitest';
import {
	emptyFilter,
	filterKey,
	fromSearchParams,
	isEmpty,
	isIsoDate,
	normalizeFilter,
	toSearchParams,
	type LedgerFilterState
} from './filter.js';

function url(filter: Partial<LedgerFilterState>): string {
	return toSearchParams({ ...emptyFilter(), ...filter }).toString();
}

describe('emptyFilter and isEmpty', () => {
	it('an empty filter has no parameters and is empty', () => {
		expect(url({})).toBe('');
		expect(isEmpty(emptyFilter())).toBe(true);
	});

	it('any dimension makes it non-empty', () => {
		expect(isEmpty({ ...emptyFilter(), q: 'rewe' })).toBe(false);
		expect(isEmpty({ ...emptyFilter(), account_id: [1] })).toBe(false);
		expect(isEmpty({ ...emptyFilter(), uncategorised: true })).toBe(false);
		expect(isEmpty({ ...emptyFilter(), flag: ['waiting'] })).toBe(false);
	});

	it('blank text, an invalid date and "exact" without a category count as empty', () => {
		expect(isEmpty({ ...emptyFilter(), q: '   ', from: 'soon', category_descendants: false })).toBe(
			true
		);
	});
});

describe('toSearchParams', () => {
	it('uses the API names, repeated for arrays', () => {
		expect(url({ from: '2026-10-01', to: '2026-10-31', account_id: [1, 2], tag_id: [9] })).toBe(
			'from=2026-10-01&to=2026-10-31&account_id=1&account_id=2&tag_id=9'
		);
	});

	it('is canonical: ids sorted and deduplicated, a fixed order whatever the input order', () => {
		expect(url({ account_id: [3, 1, 3, 2] })).toBe('account_id=1&account_id=2&account_id=3');
		const a = url({ q: 'x', from: '2026-01-01', flag: ['waiting', 'unconfirmed'] });
		const b = url({ flag: ['unconfirmed', 'waiting'], from: '2026-01-01', q: 'x' });
		expect(a).toBe(b);
		expect(a).toBe('from=2026-01-01&q=x&flag=unconfirmed&flag=waiting');
	});

	it('writes the category flags only away from their defaults', () => {
		expect(url({ category_id: [4] })).toBe('category_id=4');
		expect(url({ category_id: [4], category_descendants: false })).toBe(
			'category_id=4&category_descendants=false'
		);
		expect(url({ uncategorised: true })).toBe('uncategorised=true');
	});

	it('pairs an amount range with its currency, and drops a range without one', () => {
		expect(url({ amount_min: 500, amount_max: 2000, currency: 'eur', direction: 'out' })).toBe(
			'amount_min=500&amount_max=2000&currency=EUR&direction=out'
		);
		expect(url({ amount_min: 500 })).toBe('');
		expect(url({ currency: 'EUR' })).toBe('currency=EUR');
	});

	it('keeps a zero amount bound', () => {
		expect(url({ amount_min: 0, currency: 'EUR' })).toBe('amount_min=0&currency=EUR');
	});

	it('swaps a reversed date range and a reversed amount range', () => {
		expect(url({ from: '2026-10-31', to: '2026-10-01' })).toBe('from=2026-10-01&to=2026-10-31');
		expect(url({ amount_min: 900, amount_max: 100, currency: 'EUR' })).toBe(
			'amount_min=100&amount_max=900&currency=EUR'
		);
	});

	it('encodes the text and trims it', () => {
		expect(url({ q: '  café & bar ' })).toBe('q=caf%C3%A9+%26+bar');
	});

	it('cuts the text at the length the API accepts', () => {
		const params = toSearchParams({ ...emptyFilter(), q: 'a'.repeat(300) });
		expect(params.get('q')).toHaveLength(200);
	});
});

describe('fromSearchParams', () => {
	it('reads what toSearchParams wrote, for a rich filter', () => {
		const filter: LedgerFilterState = {
			from: '2026-10-01',
			to: '2026-10-11',
			account_id: [1, 4],
			category_id: [7],
			category_descendants: false,
			uncategorised: true,
			payee_id: [2],
			tag_id: [3, 5],
			amount_min: 100,
			amount_max: 5000,
			currency: 'EUR',
			direction: 'in',
			q: 'rewe markt',
			type: ['flow', 'transfer'],
			flag: ['unconfirmed', 'unclassified']
		};
		expect(fromSearchParams(toSearchParams(filter))).toEqual(filter);
	});

	it('round trips an empty filter and accepts a string with or without the question mark', () => {
		expect(fromSearchParams('')).toEqual(emptyFilter());
		expect(fromSearchParams('?account_id=2&q=a+b')).toEqual({
			...emptyFilter(),
			account_id: [2],
			q: 'a b'
		});
		expect(fromSearchParams('account_id=2')).toEqual({ ...emptyFilter(), account_id: [2] });
	});

	it('is stable: reading a canonical URL and writing it again gives the same URL', () => {
		const text = 'from=2026-10-01&account_id=1&account_id=2&q=x&flag=waiting';
		expect(toSearchParams(fromSearchParams(text)).toString()).toBe(text);
	});

	it('ignores unknown parameters', () => {
		expect(fromSearchParams('utm_source=x&limit=5&offset=10&foo=bar')).toEqual(emptyFilter());
	});

	it('ignores invalid dates, and keeps the valid one', () => {
		expect(fromSearchParams('from=yesterday&to=2026-10-11')).toEqual({
			...emptyFilter(),
			to: '2026-10-11'
		});
		expect(fromSearchParams('from=2026-02-30').from).toBeUndefined();
		expect(fromSearchParams('from=2026-1-1').from).toBeUndefined();
	});

	it('ignores invalid ids and keeps the valid ones', () => {
		expect(
			fromSearchParams('account_id=abc&account_id=2&account_id=-1&account_id=0&account_id=1.5')
				.account_id
		).toEqual([2]);
		expect(fromSearchParams('tag_id=&tag_id=3').tag_id).toEqual([3]);
		expect(fromSearchParams('payee_id=99999999999999999999').payee_id).toEqual([]);
	});

	it('deduplicates and sorts ids', () => {
		expect(fromSearchParams('account_id=3&account_id=1&account_id=3').account_id).toEqual([1, 3]);
	});

	it('ignores unknown types and flags, keeping the known ones in a fixed order', () => {
		const filter = fromSearchParams('type=gift&type=transfer&type=flow&flag=waiting&flag=nonsense');
		expect(filter.type).toEqual(['flow', 'transfer']);
		expect(filter.flag).toEqual(['waiting']);
	});

	it('ignores an invalid direction', () => {
		expect(fromSearchParams('direction=sideways').direction).toBeUndefined();
		expect(fromSearchParams('direction=out').direction).toBe('out');
	});

	it('drops an amount range that has no currency, or an invalid one', () => {
		expect(fromSearchParams('amount_min=100&amount_max=200')).toEqual(emptyFilter());
		expect(fromSearchParams('amount_min=100&currency=EURO').amount_min).toBeUndefined();
		expect(fromSearchParams('amount_min=-5&currency=EUR').amount_min).toBeUndefined();
		expect(fromSearchParams('amount_min=1.5&currency=EUR').amount_min).toBeUndefined();
	});

	it('keeps an amount range with its currency, in upper case', () => {
		expect(fromSearchParams('amount_min=100&currency=usd')).toMatchObject({
			amount_min: 100,
			currency: 'USD'
		});
	});

	it('reads the category flags: descendants on unless "false", uncategorised only if "true"', () => {
		expect(fromSearchParams('category_id=1').category_descendants).toBe(true);
		expect(fromSearchParams('category_id=1&category_descendants=false').category_descendants).toBe(
			false
		);
		expect(fromSearchParams('category_id=1&category_descendants=maybe').category_descendants).toBe(
			true
		);
		// "exact" without a category is meaningless and not kept
		expect(fromSearchParams('category_descendants=false').category_descendants).toBe(true);
		expect(fromSearchParams('uncategorised=true').uncategorised).toBe(true);
		expect(fromSearchParams('uncategorised=yes').uncategorised).toBe(false);
	});

	it('uses the first value of a single-valued parameter', () => {
		expect(fromSearchParams('q=a&q=b').q).toBe('a');
	});

	it('never throws, whatever it is given', () => {
		const junk = '%E0%A4%A&&&=&a=%&from=%00&q=%F0%9F%98%80&account_id=%';
		expect(() => fromSearchParams(junk)).not.toThrow();
	});
});

describe('normalizeFilter, filterKey, isIsoDate', () => {
	it('is idempotent', () => {
		const messy = {
			...emptyFilter(),
			account_id: [5, 5, 2, -1],
			from: '2026-12-31',
			to: '2026-01-01',
			q: ' x '
		};
		const once = normalizeFilter(messy);
		expect(normalizeFilter(once)).toEqual(once);
	});

	it('gives equal keys to equal filters whatever the input order', () => {
		expect(filterKey({ ...emptyFilter(), account_id: [2, 1] })).toBe(
			filterKey({ ...emptyFilter(), account_id: [1, 2] })
		);
		expect(filterKey({ ...emptyFilter(), account_id: [1] })).not.toBe(filterKey(emptyFilter()));
	});

	it('knows a calendar date from a look-alike', () => {
		expect(isIsoDate('2026-10-11')).toBe(true);
		expect(isIsoDate('2028-02-29')).toBe(true);
		expect(isIsoDate('2026-02-29')).toBe(false);
		expect(isIsoDate('2026-13-01')).toBe(false);
		expect(isIsoDate(20261011)).toBe(false);
		expect(isIsoDate(undefined)).toBe(false);
	});
});
