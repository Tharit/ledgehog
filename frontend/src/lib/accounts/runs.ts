// What an account page's run row says (ux/views/account.md "Runs"), as words: the status and the
// one line of the run's summary. The statistics are the server's; nothing is computed.
import type { ImportRun } from '#lib/api/index.js';

// components name the type from here (they never import the API)
export type { ImportRun };

export function statusLabel(status: ImportRun['status']): string {
	switch (status) {
		case 'ok':
			return 'Succeeded';
		case 'failed':
			return 'Failed';
		case 'reverted':
			return 'Reverted';
		default:
			return 'Running';
	}
}

/** "12 inserted · 2 as duplicates · 40 skipped"; empty for a run that stored no statistics. */
export function summaryLine(run: Pick<ImportRun, 'stats'>): string {
	const { inserted, inserted_as_duplicates: duplicates, skipped_by_identity: skipped } = run.stats;
	if (inserted === undefined) return '';
	return [
		`${inserted} inserted`,
		`${duplicates?.length ?? 0} as duplicates`,
		`${skipped ?? 0} skipped`
	].join(' · ');
}
