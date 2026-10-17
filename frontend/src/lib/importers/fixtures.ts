// Test fixtures for the importer screens: whole objects with the defaults a screen reads.
import type {
	CatalogEntry,
	DryRunReport,
	ImportRun,
	ImporterInstance,
	LinkResult,
	UploadResult
} from '#lib/api/importers.js';

export function catalogEntry(over: Partial<CatalogEntry> = {}): CatalogEntry {
	return {
		name: 'csv',
		kind: 'file',
		emits: ['transactions'],
		presets: { giro_with_preamble: { booked_on: 'Buchungstag' } },
		...over
	};
}

export function instance(over: Partial<ImporterInstance> = {}): ImporterInstance {
	return {
		id: 1,
		importer: 'csv',
		label: 'Giro',
		emits: ['transactions'],
		access: 'shared',
		owner_id: null,
		settings: {},
		disabled: false,
		last_run_at: null,
		accounts: [],
		...over
	};
}

export function link(over: Partial<LinkResult> = {}): LinkResult {
	return {
		instance_id: 1,
		account_id: 7,
		external_ref: 'acct-7',
		dry_run: true,
		user_authored_count: 0,
		first_booked_on: null,
		last_booked_on: null,
		account_becomes_synced: true,
		warnings: [],
		changes: [],
		settle: null,
		...over
	};
}

const category = { count: 0, examples: [] };

export function report(over: Partial<DryRunReport> = {}): DryRunReport {
	return {
		header_line: 3,
		encoding: 'utf-8',
		delimiter: ';',
		columns: [{ field: 'booked_on', name: 'Buchungstag', index: 1 }],
		rows_read: 4,
		emitted: 3,
		skipped: category,
		filtered: category,
		zero_dropped: category,
		currency_mismatch: category,
		sample: [],
		coverage: '2026-03-29',
		coverage_source: 'the last booking',
		export_date: '2026-04-02',
		export_date_source: 'the upload date',
		balance: null,
		synthetic: null,
		warnings: [],
		failure: null,
		...over
	};
}

export function run(over: Partial<ImportRun> = {}): ImportRun {
	return {
		id: 5,
		importer: 'csv',
		instance_id: 1,
		account_id: 7,
		kind: 'transactions',
		status: 'ok',
		started_at: '2026-04-02T10:00:00Z',
		finished_at: '2026-04-02T10:00:01Z',
		started_by: 1,
		error_text: null,
		covered_from: '2026-03-03',
		covered_through: '2026-03-29',
		stats: {
			inserted: 3,
			skipped_by_identity: 0,
			inserted_as_duplicates: [],
			importer: {},
			unexplained_difference: { before: null, after: null },
			since_zero: []
		},
		reverted_at: null,
		reverted_by: null,
		revertible: true,
		...over
	};
}

export function upload(over: Partial<UploadResult> = {}): UploadResult {
	return {
		run_id: null,
		dry_run: true,
		summary: run().stats,
		report: report(),
		settle: null,
		failure: null,
		importer_stats: {},
		...over
	};
}
