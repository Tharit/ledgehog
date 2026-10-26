// Importers (spec §5.1–§5.4, architecture §4.1): the catalog, instances and their links, the file
// upload with its dry run, and the run list with revert. Only the catalog entry and the request
// bodies are typed by OpenAPI; the answers below are serialised dynamically on the server, so their
// shapes are written here from app/core/importers/{instances,runs,upload}.py,
// app/core/plugins/importer.py (the dry-run report) and app/core/ingest/{run,revert}.py.
//
// Amounts are integer minor units. The server writes a `currency` next to an amount only where the
// amount is not null, so a screen that must show one always takes the account's currency itself.
import { ApiError, request } from './http.js';
import { locationPath } from './rules.js';
import type { IsoDate, SettleOut } from './types.js';

type Schemas = import('../types/api.js').components['schemas'];

/** One importer this deployment registers; `presets` is by name, each the settings it fills. */
export type CatalogEntry = Schemas['CatalogEntryOut'];
export type ImporterKind = CatalogEntry['kind'];
/** The importer's own settings: a CSV profile (a plain object, `plugins/importers/csv.md` §1). */
export type ImporterSettings = Record<string, unknown>;

export type LinkedAccount = { account_id: number; external_ref: string };

export type ImporterInstance = {
	id: number;
	importer: string;
	label: string;
	emits: ('transactions' | 'documents' | 'rates')[];
	/** whose login: `owner` (only its owner runs it) or `shared`; a file importer is always shared */
	access: 'owner' | 'shared';
	owner_id: number | null;
	/** the owner's display name; null for a shared instance */
	owner_name: string | null;
	/** whether this user may run and manage it (spec §5.11); false is the other user's login: read-only */
	manageable: boolean;
	settings: ImporterSettings;
	disabled: boolean;
	/** an ISO instant; null when it never ran */
	last_run_at: string | null;
	accounts: LinkedAccount[];
};

export type InstanceFields = {
	label: string;
	settings: ImporterSettings;
};

/** What a link does or would do (the dry run and the real link have this one shape). */
export type LinkResult = {
	instance_id: number;
	account_id: number;
	external_ref: string;
	dry_run: boolean;
	/** user-authored rows the account holds (counter-legs included) */
	user_authored_count: number;
	first_booked_on: IsoDate | null;
	last_booked_on: IsoDate | null;
	account_becomes_synced: boolean;
	warnings: string[];
	changes: string[];
	settle: SettleOut | null;
};

// ---- the dry-run report (app/core/plugins/importer.py) ---------------------------------------

export type ReportExample = { row: number; reason: string };
export type ReportCategory = { count: number; examples: ReportExample[] };
export type ReportColumn = { field: string; name: string; index: number };
export type ReportSampleRow = {
	row: number;
	booked_on: IsoDate;
	amount_minor: number;
	cells: string[];
};
export type ReportBalance = {
	amount_minor: number;
	dated_on: IsoDate;
	/** where the figure was found, in words */
	source: string;
	figure_minor: number;
	figure_on: IsoDate;
	rolled_back_by_minor: number;
	rolled_back_rows: number;
};
export type ReportSynthetic = {
	amount_minor: number;
	booked_on: IsoDate;
	row_count: number;
	sum_minor: number;
};

/** What a parse did, safe to show: counts, mapped columns, examples; never the preamble. */
export type DryRunReport = {
	header_line: number | null;
	encoding: string | null;
	delimiter: string | null;
	columns: ReportColumn[];
	rows_read: number;
	emitted: number;
	skipped: ReportCategory;
	filtered: ReportCategory;
	zero_dropped: ReportCategory;
	currency_mismatch: ReportCategory;
	sample: ReportSampleRow[];
	coverage: IsoDate | null;
	coverage_source: string | null;
	export_date: IsoDate | null;
	export_date_source: string | null;
	balance: ReportBalance | null;
	synthetic: ReportSynthetic | null;
	warnings: string[];
	failure: string | null;
};

// ---- runs (app/core/ingest/run.py stats, app/core/importers/runs.py) --------------------------

/** The statistics a run stores (spec §5.10); a failed run stores none (`{}`). */
export type RunStats = {
	inserted: number;
	skipped_by_identity: number;
	/** each row inserted as a duplicate, and the row it duplicates */
	inserted_as_duplicates: { id: number; duplicate_of: number }[];
	/** the importer's own counts: zero bookings it dropped, a statement payment it did not emit, the outcomes of an email run */
	importer: Record<string, number>;
	/** a documents run: documents already stored that the run read again (`inserted` counts the new) */
	updated?: number;
	unexplained_difference: { before: number | null; after: number | null; currency?: string };
	/** the reported balance records since the difference began (empty without one) */
	since_zero: number[];
	/** the balance record the run wrote; absent when the file reported none */
	balance?: { balance_on: IsoDate; balance: number; currency?: string };
};

export type RunStatus = 'running' | 'ok' | 'failed' | 'reverted';

export type ImportRun = {
	id: number;
	importer: string;
	instance_id: number | null;
	account_id: number | null;
	kind: 'transactions' | 'documents' | 'rates';
	status: RunStatus;
	started_at: string;
	finished_at: string | null;
	started_by: number | null;
	/** a failed run's error: its class and message ("ParseFailed: …"), never file content */
	error_text: string | null;
	/** a failed run: whether running it again can help (its error class says); null otherwise */
	retryable: boolean | null;
	covered_from: IsoDate | null;
	covered_through: IsoDate | null;
	/** `{}` for a run that failed or still runs */
	stats: Partial<RunStats>;
	reverted_at: string | null;
	reverted_by: number | null;
	/** the account's latest successful run: the only one that can be reverted */
	revertible: boolean;
};

export type RunFilter = {
	accountId?: number;
	instanceId?: number;
	status?: RunStatus;
	limit?: number;
};

export type RevertResult = {
	run_id: number;
	removed_entry_ids: number[];
	/** how many of the removed entries are confirmed (no `unconfirmed` flag), counted by the server */
	removed_confirmed: number;
	/** unpaired and returned to review */
	partner_entry_ids: number[];
	/** how many of the unpaired entries are confirmed */
	partner_confirmed: number;
	/** (row id, its new original) */
	repointed_source_ids: [number, number][];
	/** rows that stopped being duplicates and now have an entry */
	cleared_duplicate_ids: number[];
	derived_changes: unknown[];
	/** entry id → version, for every entry the revert writes (keys arrive as strings) */
	versions: Record<string, number>;
	settle: SettleOut | null;
};

// ---- upload ----------------------------------------------------------------------------------

/**
 * Why the real run would end in an error (a dry run answers 200 with it). `kind` is
 * `parse_failed`, `invalid_profile`, `importer_error`, `contract_violation` or a refusal that
 * appeared after the checks (`instance_disabled`, `account_closed`, `account_not_linked`, …);
 * `rule` names the broken contract rule (`currency_mismatch`).
 */
export type UploadFailure = { kind: string; rule: string | null; message: string };

export type UploadResult = {
	/** null on a dry run */
	run_id: number | null;
	dry_run: boolean;
	/** the run's stats as stored; `{}` when `failure` is set */
	summary: Partial<RunStats>;
	report: DryRunReport;
	settle: SettleOut | null;
	failure: UploadFailure | null;
	importer_stats: Record<string, number>;
};

// ---- calls -----------------------------------------------------------------------------------

/** What a new instance can be made from: each importer, whether it takes a file or fetches. */
export function listImporters(signal?: AbortSignal): Promise<CatalogEntry[]> {
	return request('GET', '/api/importers', { signal });
}

export function listInstances(signal?: AbortSignal): Promise<ImporterInstance[]> {
	return request('GET', '/api/importers/instances', { signal });
}

/**
 * Add an instance. A file importer holds no login (it is always shared), so no `access` is sent.
 * 422 `invalid_profile` names the setting, 422 `invalid_instance` a blank label.
 */
export function createInstance(
	importer: string,
	fields: InstanceFields,
	signal?: AbortSignal
): Promise<ImporterInstance> {
	return request('POST', '/api/importers/instances', {
		body: { importer, label: fields.label, settings: fields.settings },
		signal
	});
}

/** Change what is given (label, settings, disabled); later uploads use it, stored rows do not change. */
export function updateInstance(
	id: number,
	changes: Partial<InstanceFields> & { disabled?: boolean },
	signal?: AbortSignal
): Promise<ImporterInstance> {
	return request('PUT', `/api/importers/instances/${id}`, { body: changes, signal });
}

/** Clear what the importer remembers (a login's state); the settings stay. */
export function resetInstance(id: number): Promise<ImporterInstance> {
	return request('POST', `/api/importers/instances/${id}/reset`);
}

/** Delete an instance that never ran; its links go with it. 409 `instance_has_runs` otherwise. */
export function deleteInstance(id: number): Promise<{ settle: SettleOut }> {
	return request('DELETE', `/api/importers/instances/${id}`);
}

/**
 * Link an account (a file importer takes no reference; a fetch importer's link carries the one
 * discovery found, `externalRef`). `dryRun` previews what it would do and writes nothing. 409
 * `account_closed`, `instance_disabled`, `already_linked`.
 */
export function linkAccount(
	instanceId: number,
	accountId: number,
	{
		dryRun = false,
		externalRef,
		signal
	}: { dryRun?: boolean; externalRef?: string; signal?: AbortSignal } = {}
): Promise<LinkResult> {
	return request('POST', `/api/importers/instances/${instanceId}/links`, {
		body: {
			account_id: accountId,
			dry_run: dryRun,
			...(externalRef !== undefined ? { external_ref: externalRef } : {})
		},
		signal
	});
}

/** Remove the link; the coverage of past runs and the rows stay. */
export function unlinkAccount(
	instanceId: number,
	accountId: number
): Promise<{ settle: SettleOut }> {
	return request('DELETE', `/api/importers/instances/${instanceId}/links/${accountId}`);
}

/**
 * Upload one file for one linked account (multipart: `file`, `account_id`, `dry_run`). A dry run
 * parses and previews and writes nothing; a failure it would end in comes back as `failure`. A real
 * upload that fails is 422 `parse_failed` (`details.report`), `invalid_profile` or
 * `contract_violation`; 413 `file_too_large`; 409 `account_closed`, `account_not_linked`,
 * `instance_disabled`, `not_a_file_source`.
 */
export function uploadFile(
	instanceId: number,
	{
		file,
		accountId,
		dryRun = false,
		signal
	}: { file: Blob; accountId: number; dryRun?: boolean; signal?: AbortSignal }
): Promise<UploadResult> {
	const body = new FormData();
	body.append('file', file);
	body.append('account_id', String(accountId));
	body.append('dry_run', dryRun ? 'true' : 'false');
	return request('POST', `/api/importers/instances/${instanceId}/upload`, { body, signal });
}

/** Runs, newest first, optionally of one account, one instance or one status. */
export function listRuns(filter: RunFilter = {}, signal?: AbortSignal): Promise<ImportRun[]> {
	return request('GET', '/api/importers/runs', {
		query: {
			account_id: filter.accountId,
			instance_id: filter.instanceId,
			status: filter.status,
			limit: filter.limit
		},
		signal
	});
}

export function getRun(id: number, signal?: AbortSignal): Promise<ImportRun> {
	return request('GET', `/api/importers/runs/${id}`, { signal });
}

/**
 * Revert the account's latest successful run. `dryRun` reports what it would remove or unpair and
 * the versions to carry; the real request sends them back as `expectedVersions` (entry id →
 * version). 409 `not_latest_run` (`details.newer_run_id`), `not_revertible`, `conflict`.
 */
export function revertRun(
	id: number,
	{
		dryRun = false,
		expectedVersions,
		signal
	}: {
		dryRun?: boolean;
		expectedVersions?: Readonly<Record<string, number>>;
		signal?: AbortSignal;
	} = {}
): Promise<RevertResult> {
	return request('POST', `/api/importers/runs/${id}/revert`, {
		body: { dry_run: dryRun, expected_versions: expectedVersions ?? null },
		signal
	});
}

// ---- errors ----------------------------------------------------------------------------------

/** One place the server refused, from a 422's `details`: the field without the leading `body`. */
export type ImporterFieldProblem = { field: string; message: string };

/** A failed importer request, routed by `code` (architecture §4.4), never by the message. */
export type ImporterError =
	| { kind: 'invalid_profile'; setting: string | null; message: string }
	| { kind: 'validation'; problems: ImporterFieldProblem[] }
	| { kind: 'invalid_instance'; message: string }
	| { kind: 'instance_has_runs' }
	| { kind: 'instance_disabled' }
	| { kind: 'not_an_account_source' }
	| { kind: 'not_a_file_source' }
	| { kind: 'account_closed' }
	| { kind: 'account_not_linked' }
	| { kind: 'already_linked' }
	| { kind: 'clearance_account' }
	| { kind: 'file_too_large' }
	| { kind: 'parse_failed'; message: string; retryable: boolean; report: DryRunReport | null }
	| { kind: 'contract_violation'; rule: string | null; message: string }
	| { kind: 'importer_error'; message: string; retryable: boolean }
	| { kind: 'not_found' }
	| { kind: 'try_again' }
	| { kind: 'unauthenticated' }
	| { kind: 'network' }
	| { kind: 'other'; status: number };

function problemsOf(details: unknown): ImporterFieldProblem[] {
	if (!Array.isArray(details)) return [];
	return details.flatMap((item) => {
		const location = (item as { location?: unknown } | null)?.location;
		const message = (item as { message?: unknown } | null)?.message;
		if (!Array.isArray(location) || location.length === 0) return [];
		const field = locationPath(location);
		return field === '' ? [] : [{ field, message: String(message ?? '') }];
	});
}

/** Sort any thrown value into the failures the importer screens distinguish. */
export function classifyImporterError(error: unknown): ImporterError {
	if (!(error instanceof ApiError)) return { kind: 'network' };
	const named = (
		error.details && !Array.isArray(error.details) && typeof error.details === 'object'
			? error.details
			: {}
	) as Record<string, unknown>;
	const retryable = named.retryable === true;
	switch (error.code) {
		case 'network_error':
			return { kind: 'network' };
		case 'unauthenticated':
			return { kind: 'unauthenticated' };
		case 'not_found':
			return { kind: 'not_found' };
		case 'try_again':
			return { kind: 'try_again' };
		case 'validation_error':
			return { kind: 'validation', problems: problemsOf(error.details) };
		case 'invalid_instance':
			return { kind: 'invalid_instance', message: error.message };
		case 'invalid_profile':
			return {
				kind: 'invalid_profile',
				setting: typeof named.setting === 'string' && named.setting !== '' ? named.setting : null,
				message: error.message
			};
		case 'instance_has_runs':
		case 'instance_disabled':
		case 'not_an_account_source':
		case 'not_a_file_source':
		case 'account_closed':
		case 'account_not_linked':
		case 'already_linked':
		case 'file_too_large':
			return { kind: error.code };
		case 'conflict':
			// a clearance account is fed by documents and never linked (spec §3.3)
			return named.reason === 'clearance_account'
				? { kind: 'clearance_account' }
				: { kind: 'other', status: error.status };
		case 'parse_failed':
			return {
				kind: 'parse_failed',
				message: error.message,
				retryable,
				report: (named.report as DryRunReport | undefined) ?? null
			};
		case 'contract_violation':
			return {
				kind: 'contract_violation',
				rule: typeof named.rule === 'string' ? named.rule : null,
				message: error.message
			};
		case 'importer_error':
			return { kind: 'importer_error', message: error.message, retryable };
		default:
			return { kind: 'other', status: error.status };
	}
}
