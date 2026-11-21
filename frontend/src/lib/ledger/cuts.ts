// Cutting an ordered list into bands (design §5, patterns §4.1): the ledger list is cut by month
// and day, and the same function cuts any other list by another key (a payee, a currency). Pure:
// it takes the items in the order they are drawn and never reorders them.

/** One way of cutting: items with the same key, side by side, are one band. */
export type Cut<T> = {
	/** what the items of one band share; the band's identity */
	key: (item: T) => string;
	/** the band's heading */
	label: (item: T) => string;
};

/** A band: its heading, and either the bands cut within it or, in the innermost, its items. */
export type Band<T> = {
	/** unique among all bands of the result (an outer band's key leads an inner one's) */
	key: string;
	label: string;
	/** the bands cut within this one; empty in the innermost level */
	bands: Band<T>[];
	/** the items of the innermost level; empty where the band holds bands */
	items: T[];
};

/**
 * Cut `items` by `cuts`, outermost first (at most two deep: design §5). A band is a run of
 * adjacent items with one key, so a key that comes back later starts a new band, and the order of
 * `items` is the order of the result read through. An item is in one band only: a unit is cut as
 * one item, by its first entry, and so is never split.
 */
export function cutBy<T>(
	items: readonly T[],
	cuts: readonly [Cut<T>] | readonly [Cut<T>, Cut<T>]
): Band<T>[] {
	return cutLevel(items, cuts, '');
}

function cutLevel<T>(items: readonly T[], cuts: readonly Cut<T>[], prefix: string): Band<T>[] {
	const [cut, ...inner] = cuts;
	const bands: Band<T>[] = [];
	let run: T[] = [];
	let runKey: string | null = null;
	const close = () => {
		if (runKey === null) return;
		const key = `${prefix}${runKey}`;
		const label = cut.label(run[0]);
		bands.push(
			inner.length > 0
				? { key, label, bands: cutLevel(run, inner, `${key}/`), items: [] }
				: { key, label, bands: [], items: run }
		);
	};
	for (const item of items) {
		const key = cut.key(item);
		if (key !== runKey) {
			close();
			run = [];
			runKey = key;
		}
		run.push(item);
	}
	close();
	return bands;
}

/** Cut a list by calendar month, then by day: the ledger list's cut. Dates are `YYYY-MM-DD`. */
export function byMonthAndDay<T>(
	dateOf: (item: T) => string,
	monthLabel: (date: string) => string,
	dayLabel: (date: string) => string
): [Cut<T>, Cut<T>] {
	return [
		{ key: (item) => dateOf(item).slice(0, 7), label: (item) => monthLabel(dateOf(item)) },
		{ key: (item) => dateOf(item), label: (item) => dayLabel(dateOf(item)) }
	];
}
