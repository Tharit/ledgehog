// The account page's reads and the duplicate routes (architecture §4.1, "The account statement",
// "Marking and clearing from the statement"). Marking is previewed (`dryRun`) and carries the
// versions the preview reported, as revert does.
import { request } from './http.js';
import type { SourceVersions } from './sources.js';
import type { MarkDuplicateOut, Provenance, SourceWriteOut, StatementPage } from './types.js';

/**
 * The account's source transactions and counting balance records, newest first, paged like the
 * ledger list. `amount` (signed minor units) keeps only the imported, non-duplicate rows of that
 * amount (the picker of "mark as duplicate of…"); the balances are computed over the whole account.
 */
export function getStatement(
	accountId: number,
	{
		limit,
		offset,
		amount,
		signal
	}: { limit?: number; offset?: number; amount?: number; signal?: AbortSignal } = {}
): Promise<StatementPage> {
	return request('GET', `/api/ledger/accounts/${accountId}/statement`, {
		query: { limit, offset, amount },
		signal
	});
}

/** One source transaction: the normalised columns, `raw`, its run and `duplicate_of`; 404 when missing. */
export function getProvenance(sourceId: number, signal?: AbortSignal): Promise<Provenance> {
	return request('GET', `/api/ledger/sources/${sourceId}`, { signal });
}

/**
 * Mark an imported row as a duplicate of `of` (another row of its account). `dryRun` writes
 * nothing and reports what would go and the versions to carry. 409 `conflict` (`details.reason`
 * `already_duplicate`, `duplicate_chain`, or entries that moved: `details.entry_ids`), 422
 * `invalid_duplicate` (`of_self`, `cross_account`, `user_authored`).
 */
export function markDuplicate(
	sourceId: number,
	of: number,
	{
		dryRun = false,
		versions,
		signal
	}: { dryRun?: boolean; versions?: SourceVersions; signal?: AbortSignal } = {}
): Promise<MarkDuplicateOut> {
	// The server treats any map as the versions the caller read, and refuses a write it does not
	// cover: a dry run, which reads them, and a call that has none send null, never an empty map.
	const supplied = !dryRun && versions !== undefined && Object.keys(versions).length > 0;
	return request('POST', `/api/ledger/sources/${sourceId}/duplicate`, {
		body: {
			of,
			dry_run: dryRun,
			expected_versions: supplied
				? Object.fromEntries(Object.entries(versions).map(([k, v]) => [k, v]))
				: null
		},
		signal
	});
}

/** Clear a row marked wrongly: it gets one new entry, in review. 409 `not_a_duplicate`. */
export function clearDuplicate(sourceId: number): Promise<SourceWriteOut> {
	return request('POST', `/api/ledger/sources/${sourceId}/not-duplicate`);
}
