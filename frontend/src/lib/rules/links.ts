import { emptyFilter, toSearchParams } from '#lib/ledger/filter.js';

export const RULES_PATH = '/settings/rules';

export function ruleUrl(id: number): string {
	return `${RULES_PATH}/${id}`;
}

/**
 * The ledger narrowed to where an entry is. The ledger has no filter by id, so this is the entry's
 * booking day in its account: a few rows, the entry among them.
 */
export function ledgerLink(row: { booked_on: string; account_id: number }): string {
	const params = toSearchParams({
		...emptyFilter(),
		from: row.booked_on,
		to: row.booked_on,
		account_id: [row.account_id]
	});
	return `/ledger?${params.toString()}`;
}
