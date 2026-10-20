// The reporting reads (architecture §4.1): read-only aggregates, every figure a `Line`. The ledger
// list's account and tag filters apply to the ones that take them.
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
