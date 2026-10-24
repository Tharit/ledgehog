// What a row of the progress says (ux/views/sync.md "Progress and report"), and the stored-run shape
// the existing run summary needs, built from the statistics a `run_finished` event carries.
import type { RunSummaryInput } from '#lib/importers/run.js';
import type { TaskItem } from './events.js';

/** What the page knows of an account, for a row: its name, colour and currency. */
export type AccountInfo = { name: string; color: string | null; currency: string };

function count(value: unknown): number {
	return typeof value === 'number' ? value : 0;
}

/** "12 inserted · 31 skipped", and "· 2 as duplicates" where there are some. */
export function itemSummary(item: TaskItem): string {
	const stats = item.stats ?? {};
	if (item.kind === 'documents') {
		return [`${count(stats.inserted)} inserted`, `${count(stats.updated)} updated`].join(' · ');
	}
	const duplicates = Array.isArray(stats.inserted_as_duplicates)
		? stats.inserted_as_duplicates.length
		: 0;
	return [
		`${count(stats.inserted)} inserted`,
		`${count(stats.skipped_by_identity)} skipped`,
		...(duplicates > 0 ? [`${duplicates} as duplicates`] : [])
	].join(' · ');
}

/**
 * A finished item as an `ok` run, for the run summary. The event carries statistics and not the
 * run's dates, so there is no coverage line; that is in the account's own run log.
 */
export function itemRun(instanceId: number, item: TaskItem): RunSummaryInput {
	return {
		account_id: item.accountId,
		kind: item.kind,
		instance_id: instanceId,
		status: 'ok',
		error_text: null,
		retryable: null,
		covered_from: null,
		covered_through: null,
		stats: (item.stats ?? {}) as RunSummaryInput['stats']
	};
}
