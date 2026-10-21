// Folding the groups of a report table: the rows are a flat, depth-first list, a group row opens
// the rows beneath it. The report tables open collapsed to their top level (reports.md), so the
// state is the set of keys that are *expanded*; `toggled` (the category tree's) flips one.
export { toggled } from '#lib/categories/tree.js';

export type Foldable = { key: string; depth: number; hasChildren: boolean };

/** The rows to draw: those under a collapsed group left out, each with whether it is expanded. */
export function foldedRows<T extends Foldable>(
	rows: readonly T[],
	expanded: ReadonlySet<string>
): (T & { expanded: boolean })[] {
	const shown: (T & { expanded: boolean })[] = [];
	// the depth of the collapsed group whose rows are being skipped
	let hidingBelow: number | null = null;
	for (const row of rows) {
		if (hidingBelow !== null) {
			if (row.depth > hidingBelow) continue;
			hidingBelow = null;
		}
		const open = row.hasChildren && expanded.has(row.key);
		shown.push({ ...row, expanded: open });
		if (row.hasChildren && !open) hidingBelow = row.depth;
	}
	return shown;
}
