// The ledger filter as state and as a URL. The parameter names are the API's own, so a ledger URL
// is also an API query (`?from=2026-10-01&account_id=2`). Whatever arrives from a URL is
// validated and never thrown on: a value that cannot be understood is ignored. Serialising is
// canonical (fixed parameter order, sorted ids, defaults left out), so the same filter is always
// the same URL.

import { filterQuery } from '#lib/api/entries.js';
import type { EntryFilter } from '#lib/types/domain.js';

export type LedgerFilterState = EntryFilter;

export const ENTRY_TYPES = ['flow', 'transfer', 'opening', 'valuation', 'reconciliation'] as const;
export const REVIEW_FLAGS = [
	'unconfirmed',
	'unclassified',
	'waiting',
	'unmatched_transfer'
] as const;

/** The API refuses a longer search text. */
export const MAX_TEXT_LENGTH = 200;

export function emptyFilter(): LedgerFilterState {
	return {
		account_id: [],
		category_id: [],
		category_descendants: true,
		uncategorised: false,
		payee_id: [],
		tag_id: [],
		q: '',
		type: [],
		flag: []
	};
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** A real calendar date, `YYYY-MM-DD` (2026-02-30 is not one). */
export function isIsoDate(value: unknown): value is string {
	if (typeof value !== 'string') return false;
	const match = ISO_DATE.exec(value);
	if (!match) return false;
	const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
	const date = new Date(Date.UTC(year, month - 1, day));
	return (
		date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
	);
}

function cleanIds(values: readonly unknown[]): number[] {
	const found = new Set<number>();
	for (const value of values) {
		if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0) found.add(value);
	}
	return [...found].sort((a, b) => a - b);
}

function cleanTokens(values: readonly unknown[], known: readonly string[]): string[] {
	return known.filter((token) => values.includes(token));
}

function cleanBound(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : undefined;
}

/** The canonical form of a filter: invalid parts dropped, the rest ordered and deduplicated. */
export function normalizeFilter(filter: LedgerFilterState): LedgerFilterState {
	let from = isIsoDate(filter.from) ? filter.from : undefined;
	let to = isIsoDate(filter.to) ? filter.to : undefined;
	if (from && to && from > to) [from, to] = [to, from];

	const category_id = cleanIds(filter.category_id);

	let amount_min = cleanBound(filter.amount_min);
	let amount_max = cleanBound(filter.amount_max);
	const currency =
		typeof filter.currency === 'string' && /^[A-Za-z]{3}$/.test(filter.currency)
			? filter.currency.toUpperCase()
			: undefined;
	// an amount bound only means something in one currency (the API refuses it otherwise)
	if (!currency) amount_min = amount_max = undefined;
	if (amount_min !== undefined && amount_max !== undefined && amount_min > amount_max) {
		[amount_min, amount_max] = [amount_max, amount_min];
	}

	const text = typeof filter.q === 'string' ? filter.q.trim().slice(0, MAX_TEXT_LENGTH).trim() : '';

	return {
		from,
		to,
		account_id: cleanIds(filter.account_id),
		category_id,
		// "exact" only means something next to a category
		category_descendants: category_id.length === 0 ? true : filter.category_descendants !== false,
		uncategorised: filter.uncategorised === true,
		payee_id: cleanIds(filter.payee_id),
		tag_id: cleanIds(filter.tag_id),
		amount_min,
		amount_max,
		currency,
		direction:
			filter.direction === 'in' || filter.direction === 'out' ? filter.direction : undefined,
		q: text,
		type: cleanTokens(filter.type, ENTRY_TYPES),
		flag: cleanTokens(filter.flag, REVIEW_FLAGS)
	};
}

/** The filter as URL parameters; the same names, order and defaults as the API query. */
export function toSearchParams(filter: LedgerFilterState): URLSearchParams {
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(filterQuery(normalizeFilter(filter)))) {
		for (const item of Array.isArray(value) ? value : [value]) {
			if (item !== undefined && item !== null) params.append(key, String(item));
		}
	}
	return params;
}

/** A stable identity for a filter: equal filters give equal keys. */
export function filterKey(filter: LedgerFilterState): string {
	return toSearchParams(filter).toString();
}

function integer(text: string): number | undefined {
	return /^\d{1,15}$/.test(text) ? Number(text) : undefined;
}

function integers(texts: string[]): number[] {
	return texts.map(integer).filter((n): n is number => n !== undefined);
}

/** A filter from a query string; anything unknown or invalid is ignored, never thrown on. */
export function fromSearchParams(input: URLSearchParams | string): LedgerFilterState {
	const params = typeof input === 'string' ? new URLSearchParams(input) : input;
	const first = (name: string) => params.get(name) ?? undefined;
	const bound = first('amount_min');
	const bound2 = first('amount_max');
	return normalizeFilter({
		from: first('from'),
		to: first('to'),
		account_id: integers(params.getAll('account_id')),
		category_id: integers(params.getAll('category_id')),
		category_descendants: !['false', '0'].includes(first('category_descendants') ?? ''),
		uncategorised: ['true', '1'].includes(first('uncategorised') ?? ''),
		payee_id: integers(params.getAll('payee_id')),
		tag_id: integers(params.getAll('tag_id')),
		amount_min: bound === undefined ? undefined : integer(bound),
		amount_max: bound2 === undefined ? undefined : integer(bound2),
		currency: first('currency'),
		direction: first('direction') as LedgerFilterState['direction'],
		q: first('q') ?? '',
		type: params.getAll('type'),
		flag: params.getAll('flag')
	});
}

/** No filter at all (an invalid or meaningless part counts as none). */
export function isEmpty(filter: LedgerFilterState): boolean {
	return filterKey(filter) === '';
}
