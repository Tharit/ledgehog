// Columns as wide as what they hold (patterns §4.1): a pure allocation of a row's width over its
// columns, from the widest content measured in each. No DOM here; the measuring is
// components/ledger/column-sizer.svelte.ts.

export type SizingColumn = {
	id: string;
	/** fixed: `width`; flex / fill: between floor and min(measured, cap), the widest shrink first */
	kind: 'fixed' | 'flex' | 'fill';
	/** fixed: its width in px */
	width?: number;
	/** flex / fill: the widest content in px */
	measured?: number;
	floor?: number;
	cap?: number;
};

/**
 * The width in px of every column (same order). `available` is the room for the tracks alone.
 * Fixed columns keep their width. Every flex / fill column wants min(measured, cap): when all
 * of that fits, each gets it and the fill column takes the rest. When not, the widest shrink
 * first: one common ceiling L is found (exactly) such that the sum of
 * max(floor, min(desired, L)) equals the room, so short columns stay complete as long as
 * possible and no column goes below its floor. When even the floors do not fit, all sit at floor.
 */
export function sizeColumns(available: number, columns: readonly SizingColumn[]): number[] {
	const widths = columns.map((c) => (c.kind === 'fixed' ? (c.width ?? 0) : 0));
	const flexible = columns.flatMap((c, i) => (c.kind === 'fixed' ? [] : [i]));
	const desired = new Map<number, number>();
	const floor = new Map<number, number>();
	for (const i of flexible) {
		const c = columns[i];
		const want = Math.min(c.measured ?? 0, c.cap ?? Infinity);
		desired.set(i, want);
		// never below its content when that is smaller than the floor
		floor.set(i, Math.min(c.floor ?? 0, want));
	}
	const room = available - widths.reduce((a, b) => a + b, 0);
	const fill = columns.findIndex((c) => c.kind === 'fill');
	const wanted = flexible.reduce((sum, i) => sum + desired.get(i)!, 0);
	if (wanted <= room) {
		for (const i of flexible) widths[i] = desired.get(i)!;
		if (fill >= 0) widths[fill] += room - wanted;
		return widths;
	}
	const at = (level: number) =>
		flexible.reduce((sum, i) => sum + Math.max(floor.get(i)!, Math.min(desired.get(i)!, level)), 0);
	const minimum = flexible.reduce((sum, i) => sum + floor.get(i)!, 0);
	let level = 0;
	if (minimum < room) {
		// the sum is piecewise linear in the level, bending at the floors and desired widths:
		// find the segment holding the room and interpolate in it
		const points = [...new Set(flexible.flatMap((i) => [floor.get(i)!, desired.get(i)!]))].sort(
			(a, b) => a - b
		);
		let lo = points[0];
		for (const hi of points.slice(1)) {
			if (at(hi) >= room) {
				const from = at(lo);
				level = lo + ((room - from) / (at(hi) - from)) * (hi - lo);
				break;
			}
			lo = hi;
		}
	}
	for (const i of flexible) {
		widths[i] = Math.max(floor.get(i)!, Math.min(desired.get(i)!, level));
	}
	return widths;
}

/**
 * The grid-template-columns value for `columns` in a row `available` px wide (tracks alone, the
 * padding and gaps already taken off). Every track is in px; where all the columns get what they
 * want, the fill column's track is `minmax(px, 1fr)` so it grows with the row between measurings.
 * Tracks are floored to whole px, the fill column taking the rounding leftover when shrinking.
 *
 * `keep` names the columns of a grid that has fewer than `columns` (the review queue's pending
 * section has no date column): the allocation is still made over all of `columns`, so the columns
 * kept come out as wide as in a grid that has them all, and the fill column takes the width of the
 * ones dropped, with the `gap` that went with each, so the row stays full.
 */
export function trackTemplate(
	available: number,
	columns: readonly SizingColumn[],
	keep?: readonly string[],
	gap = 0
): string {
	const px = sizeColumns(available, columns).map((w) => Math.floor(w));
	const fill = columns.findIndex((c) => c.kind === 'fill');
	const wanted = columns.reduce(
		(sum, c) =>
			sum + (c.kind === 'fixed' ? (c.width ?? 0) : Math.min(c.measured ?? 0, c.cap ?? Infinity)),
		0
	);
	const fits = wanted <= available;
	if (!fits && fill >= 0) px[fill] += Math.floor(available - px.reduce((a, b) => a + b, 0));
	if (keep && fill >= 0) {
		px[fill] += columns.reduce((sum, c, i) => (keep.includes(c.id) ? sum : sum + px[i] + gap), 0);
	}
	return columns
		.flatMap((c, i) =>
			keep && !keep.includes(c.id)
				? []
				: [c.kind === 'fill' && fits ? `minmax(${px[i]}px, 1fr)` : `${px[i]}px`]
		)
		.join(' ');
}
