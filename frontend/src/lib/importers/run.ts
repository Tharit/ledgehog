// What the run summary shows of a run (ux/views/importers.md "The run summary"): the one shape of a
// stored run and of a dry run, so that one component reports both.
import type { ImportRun, RunStats, UploadResult } from '#lib/api/importers.js';

/** The part of a run the summary reads; a stored `ImportRun` has it as it is. */
export type RunSummaryInput = Pick<
	ImportRun,
	| 'account_id'
	| 'kind'
	| 'instance_id'
	| 'status'
	| 'error_text'
	| 'retryable'
	| 'covered_from'
	| 'covered_through'
	| 'stats'
>;

/** A dry run's answer as a run that would end well: the same statistics, the report's coverage. */
export function dryRunAsRun(result: UploadResult, accountId: number): RunSummaryInput {
	return {
		account_id: accountId,
		kind: 'transactions',
		instance_id: null,
		status: 'ok',
		error_text: null,
		retryable: null,
		covered_from: null,
		covered_through: result.report.coverage,
		stats: result.summary
	};
}

/** The statistics with every part present; a run that failed stored none. */
export function statsOf(run: RunSummaryInput): RunStats {
	const { stats } = run;
	return {
		inserted: stats.inserted ?? 0,
		skipped_by_identity: stats.skipped_by_identity ?? 0,
		inserted_as_duplicates: stats.inserted_as_duplicates ?? [],
		importer: stats.importer ?? {},
		updated: stats.updated,
		unexplained_difference: stats.unexplained_difference ?? { before: null, after: null },
		since_zero: stats.since_zero ?? [],
		balance: stats.balance
	};
}

/** Whether a difference is a figure that is not zero (null: there is none). */
export function isDifference(minor: number | null | undefined): minor is number {
	return minor !== null && minor !== undefined && minor !== 0;
}

/**
 * What an importer counted in a documents run, in the order the summary lists them (the email
 * importer's outcomes, plugins/importers/email.md §8): the key and how it reads after the number.
 */
export const DOCUMENT_COUNTS: readonly (readonly [key: string, label: string])[] = [
	['documents', 'documents'],
	['superseded', 'superseded by a later message'],
	['incomplete', "incomplete (items don't add up)"],
	['no_merchant', 'without a merchant'],
	['unknown_currency', 'in an unknown currency'],
	['refund', 'refunds skipped'],
	['not_accepted', 'not from an allowed sender'],
	['already_seen', 'already seen'],
	['before_start', 'before the start date'],
	['too_large', 'too large'],
	['no_content', 'without content'],
	['pdf_not_read', 'PDF not read (no vision model)'],
	['unreadable', 'unreadable'],
	['model_refused', 'refused by the model'],
	['gave_up', 'given up after repeated failures']
];

/** The non-zero counts of a documents run, each with its label ("3 not from an allowed sender"). */
export function documentCounts(counts: Record<string, number>): string[] {
	return DOCUMENT_COUNTS.filter(([key]) => (counts[key] ?? 0) > 0).map(
		([key, label]) => `${counts[key]} ${label}`
	);
}
