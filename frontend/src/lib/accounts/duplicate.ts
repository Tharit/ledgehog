// Pure rules of "Mark as duplicate of…" (spec §5.6, ux/views/account.md): which rows can be the
// original, in what order, and which of the two rows is preselected as the duplicate.
import type { StatementSource } from '#lib/types/domain.js';

const MS_PER_DAY = 86_400_000;

function day(iso: string): number {
	const [y, m, d] = iso.split('-').map(Number);
	return Date.UTC(y, m - 1, d) / MS_PER_DAY;
}

/** Whole days between two calendar dates, always non-negative. */
export function dayDistance(a: string, b: string): number {
	return Math.abs(day(a) - day(b));
}

/**
 * The rows the original can be picked from: the statement's imported, non-duplicate rows of the
 * same amount (its `amount` filter) without the row itself, the nearest date first, ties by id.
 */
export function originalCandidates(
	row: Pick<StatementSource, 'id' | 'booked_on'>,
	rows: readonly StatementSource[]
): StatementSource[] {
	return rows
		.filter((r) => r.id !== row.id && !r.authored && r.duplicate_of === null)
		.sort(
			(a, b) =>
				dayDistance(a.booked_on, row.booked_on) - dayDistance(b.booked_on, row.booked_on) ||
				b.id - a.id
		);
}

/** True when `a` is the newer row: the later booking date, then the later id (spec §5.6). */
export function isNewer(
	a: Pick<StatementSource, 'id' | 'booked_on'>,
	b: Pick<StatementSource, 'id' | 'booked_on'>
): boolean {
	if (a.booked_on !== b.booked_on) return a.booked_on > b.booked_on;
	return a.id > b.id;
}
