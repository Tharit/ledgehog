// Where the unit panel steps (`[` `]`): the list it was opened from. The ledger and the review
// queue each register a `UnitSource`; the newest registration is the active one, and a source
// that goes away only unregisters itself. The panel asks the source for the neighbour and tells it
// what an action touched, so the list patches its rows in place (patterns §7).
import type { Entry } from '#lib/types/domain.js';
import type { Affected } from './types.js';

export type StepDirection = -1 | 1;

export interface UnitSource {
	/** The id of an entry of the previous (-1) or next (1) unit, or null at the end or when unknown. */
	neighbour(entryId: number, dir: StepDirection): number | null;
	/** What an action touched: patch the rows held, in place. */
	patch(affected: Affected): void;
	/**
	 * Put the list's cursor on the row of this entry and scroll it into view, without touching the
	 * list's filter, address or contents. True when the entry is in the list. The panel calls it
	 * when it opens and on each step, so the list behind the overlay follows the unit shown.
	 * `visit` false: the cursor lands there without "visiting": the marks of the row stay (the
	 * units just committed, whose marks say what the commit did).
	 */
	reveal?(entryId: number, visit?: boolean): boolean;
	/**
	 * The list ends here and has more to load: load it and say whether rows were added, so the
	 * panel can carry on advancing instead of stopping at the end of a page.
	 */
	loadMore?(): Promise<boolean>;
	/** A quiet line for the page ("Review done"): where the panel's end-of-list message goes. */
	notice?(text: string): void;
	/** What the end of this list is called ("Review done"; default "No more units"). */
	finishedText?: string;
	/** Where the unit is in the list ("12 of 214"), when the source knows. */
	position?(entryId: number): { index: number; total: number } | null;
}

let active: UnitSource | null = null;

/** Make `source` the one the panel steps through; call the returned function when it goes away. */
export function registerUnitSource(source: UnitSource): () => void {
	active = source;
	return () => {
		if (active === source) active = null;
	};
}

export function activeUnitSource(): UnitSource | null {
	return active;
}

/**
 * The neighbour among entry rows in list order: the next row (in `dir`) that is in ANOTHER unit.
 * Siblings of the same unit (one `unit_key`) are skipped, and so are entries that are in no unit
 * (derived ones have no `unit_key`). Null when `entryId` is not among the rows or none is left.
 */
export function neighbourEntry(
	entries: readonly Pick<Entry, 'id' | 'unit_key'>[],
	entryId: number,
	dir: StepDirection
): number | null {
	const from = entries.findIndex((e) => e.id === entryId);
	if (from < 0) return null;
	const own = entries[from].unit_key;
	for (let i = from + dir; i >= 0 && i < entries.length; i += dir) {
		const candidate = entries[i];
		if (candidate.unit_key === null) continue;
		if (own !== null && candidate.unit_key === own) continue;
		return candidate.id;
	}
	return null;
}
