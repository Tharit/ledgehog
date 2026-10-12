import { request, type Query } from './http.js';
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

/** How many entries `findEntry` looks through when it has nothing to narrow the search by. */
export const FIND_SCAN_LIMIT = 5000;

/**
 * One entry by id. The API has no single-entry read yet, so the list is narrowed by what the
 * caller knows (the booking date and the account) and searched for the id; without that it scans
 * the newest `FIND_SCAN_LIMIT` entries. Null when it is not found.
 */
export async function findEntry(
	id: number,
	hints: { on?: string; accountId?: number } = {},
	signal?: AbortSignal
): Promise<Entry | null> {
	const narrowed = hints.on !== undefined;
	const filter: EntryFilter = {
		account_id: hints.accountId === undefined ? [] : [hints.accountId],
		category_id: [],
		category_descendants: true,
		uncategorised: false,
		payee_id: [],
		tag_id: [],
		q: '',
		type: [],
		flag: [],
		from: hints.on,
		to: hints.on
	};
	const size = 500;
	const limit = narrowed ? 2000 : FIND_SCAN_LIMIT;
	for (let offset = 0; offset < limit; offset += size) {
		const page = await listEntries(filter, { limit: size, offset, signal });
		const found = page.entries.find((entry) => entry.id === id);
		if (found) return found;
		if (offset + size >= page.total) break;
	}
	return null;
}
