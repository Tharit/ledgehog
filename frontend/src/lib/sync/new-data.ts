// What a sync tells the views that hold data (architecture §6.4, ux/views/sync.md "New data"): that
// a run of this session wrote rows, and that a sync ended. Nothing is counted: a revision only says
// "something arrived since you looked".
import type { SyncEvent } from '#lib/api/sync.js';

/** The stored statistics of a run wrote rows: some inserted, or some inserted as duplicates. */
export function statsWroteRows(stats: Record<string, unknown> | null | undefined): boolean {
	if (!stats) return false;
	const inserted = typeof stats.inserted === 'number' ? stats.inserted : 0;
	const duplicates = Array.isArray(stats.inserted_as_duplicates)
		? stats.inserted_as_duplicates.length
		: 0;
	return inserted > 0 || duplicates > 0;
}

/** An event that says rows were written: a finished run with rows in its statistics. */
export function eventWroteRows(event: SyncEvent): boolean {
	return event.name === 'run_finished' && statsWroteRows(event.data.stats);
}
