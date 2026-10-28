import type { Entry, Money } from '#lib/types/domain.js';

// How the entries of one unit are drawn together (patterns §4.1): adjacent rows that share a
// `unit_key` are one run, framed as one block and highlighted together. Derived entries have no
// `unit_key` and are never joined. A transfer pair's legs may be days apart in the ledger; they are
// joined only when adjacent.

export type UnitRun = {
	/** the server's `unit_key` of the run; null for an entry in no unit */
	key: number | null;
	entries: readonly Entry[];
	/** a split's total, on the marker of each of its rows; null for a single entry or a pair */
	total: Money | null;
};

/** The classes of a joined run: a faint bar on the left, and a group for the joint highlight. */
export const UNIT_FRAME = 'group/unit border-l-2 border-l-primary/30';

/** A split's total: null for fewer than two entries, a transfer pair or mixed currencies. */
export function unitTotal(entries: readonly Entry[]): Money | null {
	if (entries.length < 2 || entries.some((e) => e.type === 'transfer')) return null;
	const currency = entries[0].amount.currency;
	if (entries.some((e) => e.amount.currency !== currency)) return null;
	return { amount: entries.reduce((sum, e) => sum + e.amount.amount, 0), currency };
}

/** Group `entries`, in order, into runs of adjacent entries of one unit. */
export function unitRuns(entries: readonly Entry[]): UnitRun[] {
	const runs: Entry[][] = [];
	for (const entry of entries) {
		const last = runs[runs.length - 1];
		if (last && entry.unit_key !== null && last[0].unit_key === entry.unit_key) last.push(entry);
		else runs.push([entry]);
	}
	return runs.map((run) => ({ key: run[0].unit_key, entries: run, total: unitTotal(run) }));
}
