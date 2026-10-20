// What the reporting views write around their figures: the unvalued remainder (patterns §2), the
// savings rate, month names and the links from a figure to the ledger or the report that lists
// what it sums (spec §8: the entries behind a figure are exactly the entries its drill-down lists).
import { formatMoney } from '#lib/format/index.js';
import { emptyFilter, toSearchParams, type LedgerFilterState } from '#lib/ledger/filter.js';
import type { Line } from './types.js';

/** How many entries of a line could not be valued. */
export function unvaluedCount(line: Line): number {
	return line.unvalued.reduce((sum, u) => sum + u.count, 0);
}

function entries(count: number): string {
	return count === 1 ? '1 entry' : `${count} entries`;
}

/** The tooltip of "unvalued": the currencies without a usable rate, each with its native sum. */
export function unvaluedExplanation(line: Line, locale = 'en'): string {
	const parts = line.unvalued.map((u) => {
		const native = formatMoney(u.amount.amount, u.amount.currency, {
			locale,
			showCurrency: true,
			showPlus: false
		});
		return `${native} (${entries(u.count)})`;
	});
	return parts.length === 0
		? 'No usable exchange rate.'
		: `No usable exchange rate for ${parts.join(', ')}.`;
}

/** "+ 2 unvalued": a sum that omits unvalued entries says how many. */
export function unvaluedNote(line: Line): string {
	return `+ ${unvaluedCount(line)} unvalued`;
}

/** The first day of the month `today` is in. */
export function monthStart(today: string): string {
	return `${today.slice(0, 8)}01`;
}

/** The ledger filtered as given; the same URL the ledger itself writes for that filter. */
export function ledgerHref(filter: Partial<LedgerFilterState>): string {
	const query = toSearchParams({ ...emptyFilter(), ...filter }).toString();
	return query === '' ? '/ledger' : `/ledger?${query}`;
}

/** *By category* for a range. */
export function byCategoryHref(from: string, to: string): string {
	return `/reports/by-category?${new URLSearchParams({ from, to })}`;
}

/** The transfer legs that still wait for a partner or have none (spec §6). */
export const UNPAIRED_TRANSFERS_HREF = ledgerHref({
	type: ['transfer'],
	flag: ['waiting', 'unmatched_transfer']
});
