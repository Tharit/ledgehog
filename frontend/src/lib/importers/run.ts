// What the run summary shows of a run (ux/views/importers.md "The run summary"): the one shape of a
// stored run and of a dry run, so that one component reports both.
import type { ImportRun, RunStats, UploadResult } from '#lib/api/importers.js';

/** The part of a run the summary reads; a stored `ImportRun` has it as it is. */
export type RunSummaryInput = Pick<
	ImportRun,
	'account_id' | 'status' | 'error_text' | 'covered_from' | 'covered_through' | 'stats'
>;

/** A dry run's answer as a run that would end well: the same statistics, the report's coverage. */
export function dryRunAsRun(result: UploadResult, accountId: number): RunSummaryInput {
	return {
		account_id: accountId,
		status: 'ok',
		error_text: null,
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
		unexplained_difference: stats.unexplained_difference ?? { before: null, after: null },
		since_zero: stats.since_zero ?? [],
		balance: stats.balance
	};
}

/** Whether a difference is a figure that is not zero (null: there is none). */
export function isDifference(minor: number | null | undefined): minor is number {
	return minor !== null && minor !== undefined && minor !== 0;
}
