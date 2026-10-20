import { describe, expect, it } from 'vitest';
import {
	UNPAIRED_TRANSFERS_HREF,
	byCategoryHref,
	ledgerHref,
	monthStart,
	unvaluedCount,
	unvaluedExplanation,
	unvaluedNote
} from './figures.js';
import type { Line } from './types.js';

const line = (over: Partial<Line> = {}): Line => ({ total: null, count: 3, unvalued: [], ...over });

describe('the unvalued remainder', () => {
	const usd = line({
		unvalued: [
			{ amount: { amount: 12000, currency: 'USD' }, count: 2 },
			{ amount: { amount: -500, currency: 'CHF' }, count: 1 }
		]
	});

	it('counts the entries without a rate across currencies', () => {
		expect(unvaluedCount(usd)).toBe(3);
		expect(unvaluedNote(usd)).toBe('+ 3 unvalued');
	});

	it('names each currency with its native sum and its entries', () => {
		expect(unvaluedExplanation(usd)).toBe(
			'No usable exchange rate for 120.00 USD (2 entries), −5.00 CHF (1 entry).'
		);
	});

	it('still explains a line that lists no currency', () => {
		expect(unvaluedExplanation(line())).toBe('No usable exchange rate.');
	});
});

describe('monthStart', () => {
	it('finds the first day of the month', () => {
		expect(monthStart('2026-10-20')).toBe('2026-10-01');
		expect(monthStart('2026-10-01')).toBe('2026-10-01');
	});
});

describe('links', () => {
	it('writes the ledger filter the way the ledger does', () => {
		expect(ledgerHref({ category_id: [4], from: '2026-10-01', to: '2026-10-20' })).toBe(
			'/ledger?from=2026-10-01&to=2026-10-20&category_id=4'
		);
		expect(ledgerHref({ uncategorised: true, direction: 'out', from: '2026-10-01' })).toBe(
			'/ledger?from=2026-10-01&uncategorised=true&direction=out'
		);
		expect(ledgerHref({})).toBe('/ledger');
	});

	it('leads the unpaired transfers to the legs that wait or have no partner', () => {
		expect(UNPAIRED_TRANSFERS_HREF).toBe(
			'/ledger?type=transfer&flag=waiting&flag=unmatched_transfer'
		);
	});

	it('leads a figure to the report of its range', () => {
		expect(byCategoryHref('2026-10-01', '2026-10-20')).toBe(
			'/reports/by-category?from=2026-10-01&to=2026-10-20'
		);
	});
});
