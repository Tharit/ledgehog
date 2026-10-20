// The reporting reads (architecture §4.1): read-only aggregates, every figure a `Line`. The ledger
// list's account and tag filters apply to the ones that take them.
import type { Balances, Kind, OverTime, Step } from '#lib/reports/shapes.js';
import type { ByCategory, Overview } from '#lib/reports/types.js';
import { request } from './http.js';

/** Net worth, savings, this month's spend and the accounts by data age, at the household's today. */
export function getOverview(signal?: AbortSignal): Promise<Overview> {
	return request('GET', '/api/reports/overview', { signal });
}

export type ByCategoryOptions = {
	from: string;
	to: string;
	kind?: 'expense' | 'income';
	accountIds?: readonly number[];
	tagIds?: readonly number[];
	/** the largest top-level categories as `slices`, the rest as `other` (the Overview's card) */
	top?: number;
	signal?: AbortSignal;
};

/** Spend (or income) by category over a range, as the category tree with its lines beside it. */
export function getByCategory({
	from,
	to,
	kind,
	accountIds,
	tagIds,
	top,
	signal
}: ByCategoryOptions): Promise<ByCategory> {
	return request('GET', '/api/reports/by-category', {
		query: { from, to, kind, account_id: accountIds, tag_id: tagIds, top },
		signal
	});
}

export type OverTimeOptions = {
	from: string;
	to: string;
	step?: Step;
	/** `savings`: income, expense and savings per period; `category`: each category's amount */
	mode?: 'savings' | 'category';
	kind?: Kind;
	accountIds?: readonly number[];
	tagIds?: readonly number[];
	signal?: AbortSignal;
};

/** A range cut into months, quarters or years (at most 120): the savings or the categories of each. */
export function getOverTime({
	from,
	to,
	step,
	mode,
	kind,
	accountIds,
	tagIds,
	signal
}: OverTimeOptions): Promise<OverTime> {
	return request('GET', '/api/reports/over-time', {
		query: { from, to, step, mode, kind, account_id: accountIds, tag_id: tagIds },
		signal
	});
}

/** Net worth and every account's balance at the month-ends of a range. */
export function getBalances(from: string, to: string, signal?: AbortSignal): Promise<Balances> {
	return request('GET', '/api/reports/balances', { query: { from, to }, signal });
}
