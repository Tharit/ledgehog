import { queryString, request, type Query } from './http.js';
import type { Entry, EntryFilter, EntryPage } from './types.js';

export const DEFAULT_PAGE_SIZE = 100;

/**
 * A filter as query parameters, in the API's names and in a fixed order (so the same filter is
 * always the same string). Empty values are left out and arrays are repeated parameters; a
 * parameter at its API default (`category_descendants=true`, `uncategorised=false`) is left out.
 */
export function filterQuery(filter: EntryFilter): Query {
	const text = filter.q.trim();
	return {
		from: filter.from,
		to: filter.to,
		account_id: filter.account_id,
		category_id: filter.category_id,
		category_descendants: filter.category_descendants ? undefined : false,
		uncategorised: filter.uncategorised ? true : undefined,
		payee_id: filter.payee_id,
		tag_id: filter.tag_id,
		amount_min: filter.amount_min,
		amount_max: filter.amount_max,
		currency: filter.currency,
		direction: filter.direction,
		q: text === '' ? undefined : text,
		type: filter.type,
		flag: filter.flag
	};
}

export type PageOptions = { limit?: number; offset?: number; signal?: AbortSignal };

/** One page of entries matching `filter`; `total` counts every match, whatever the page. */
export function listEntries(
	filter: EntryFilter,
	{ limit = DEFAULT_PAGE_SIZE, offset = 0, signal }: PageOptions = {}
): Promise<EntryPage> {
	return request('GET', '/api/ledger/entries', {
		query: { ...filterQuery(filter), limit, offset: offset > 0 ? offset : undefined },
		signal
	});
}

/**
 * The address of the CSV of every entry matching `filter` (the server's answer, in the list's
 * order). A link, not a request: the browser follows it and the session cookie rides along.
 */
export function exportUrl(filter: EntryFilter): string {
	return `/api/ledger/entries/export${queryString(filterQuery(filter))}`;
}

/** One entry, with its source transaction (`source`, null for a user-authored or derived one). */
export function getEntry(id: number, signal?: AbortSignal): Promise<Entry> {
	return request('GET', `/api/ledger/entries/${id}`, { signal });
}
