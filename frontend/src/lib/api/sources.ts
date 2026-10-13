// User-authored source transactions: the entry form (architecture §4.1, spec §3.9, §5.6).
// Edit and delete are previewed (`dry_run`) and carry the versions the preview reported.
import { request } from './http.js';
import type {
	SourceCreateBody,
	SourceDeleteOut,
	SourceEditOut,
	SourceUpdateBody,
	SourceWriteOut
} from './types.js';

/** What an edit changes: absent fields stay; `purpose: null` clears it. Never the account. */
export type SourceChanges = Partial<Pick<SourceUpdateBody, 'amount' | 'booked_on' | 'purpose'>>;

/** `entry_id → version`, as the preview reported them. */
export type SourceVersions = Readonly<Record<number, number>>;

/**
 * Enter a movement on an unsynced account. `body.id` is made by the form before it submits: the
 * same id sent again answers with the row already entered (200 instead of 201), so a retry after
 * a lost answer cannot enter it twice.
 */
export function createSource(
	body: SourceCreateBody,
	signal?: AbortSignal
): Promise<SourceWriteOut> {
	return request('POST', '/api/ledger/sources', { body, signal });
}

/** Edit a user-authored row; `dryRun` writes nothing and reports `effects` (with the versions to carry). */
export function updateSource(
	id: number,
	changes: SourceChanges,
	{
		dryRun = false,
		versions = {},
		signal
	}: { dryRun?: boolean; versions?: SourceVersions; signal?: AbortSignal } = {}
): Promise<SourceEditOut> {
	const body: SourceUpdateBody = {
		...changes,
		dry_run: dryRun,
		expected_versions: Object.fromEntries(Object.entries(versions).map(([k, v]) => [k, v]))
	};
	return request('PUT', `/api/ledger/sources/${id}`, { body, signal });
}

/** Delete a user-authored row with its entries; `dryRun` reports the counts and the versions. */
export function deleteSource(
	id: number,
	{
		dryRun = false,
		versions = {},
		signal
	}: { dryRun?: boolean; versions?: SourceVersions; signal?: AbortSignal } = {}
): Promise<SourceDeleteOut> {
	return request('DELETE', `/api/ledger/sources/${id}`, {
		query: {
			dry_run: dryRun,
			expected_versions: Object.entries(versions).map(([entry, version]) => `${entry}:${version}`)
		},
		signal
	});
}
