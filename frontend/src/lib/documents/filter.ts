// The documents filter as state and as a URL, in the manner of the ledger's (lib/ledger/filter.ts):
// the parameter names are the API's own, whatever arrives from a URL is validated and never thrown
// on, and serialising is canonical so the same filter is always the same URL.
import { documentQuery } from '#lib/api/documents.js';
import { formatDate, formatDateRange, formatMoney } from '#lib/format/index.js';
import { isIsoDate, MAX_TEXT_LENGTH } from '#lib/ledger/filter.js';
import type { DocumentFilter } from '#lib/types/domain.js';

export function emptyDocumentFilter(): DocumentFilter {
	return { provider: [], q: '' };
}

function cleanBound(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : undefined;
}

/** The canonical form of a filter: invalid parts dropped, the rest ordered and deduplicated. */
export function normalizeDocumentFilter(filter: DocumentFilter): DocumentFilter {
	let from = isIsoDate(filter.from) ? filter.from : undefined;
	let to = isIsoDate(filter.to) ? filter.to : undefined;
	if (from && to && from > to) [from, to] = [to, from];

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

	const providers = [
		...new Set(filter.provider.map((p) => (typeof p === 'string' ? p.trim() : '')).filter(Boolean))
	].sort();
	const text = typeof filter.q === 'string' ? filter.q.trim().slice(0, MAX_TEXT_LENGTH).trim() : '';

	return {
		provider: providers,
		from,
		to,
		amount_min,
		amount_max,
		currency,
		q: text,
		linked: typeof filter.linked === 'boolean' ? filter.linked : undefined
	};
}

/** The filter as URL parameters; the same names, order and defaults as the API query. */
export function documentSearchParams(filter: DocumentFilter): URLSearchParams {
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(documentQuery(normalizeDocumentFilter(filter)))) {
		for (const item of Array.isArray(value) ? value : [value]) {
			if (item !== undefined && item !== null) params.append(key, String(item));
		}
	}
	return params;
}

/** A stable identity for a filter: equal filters give equal keys. */
export function documentFilterKey(filter: DocumentFilter): string {
	return documentSearchParams(filter).toString();
}

function integer(text: string | undefined): number | undefined {
	return text !== undefined && /^\d{1,15}$/.test(text) ? Number(text) : undefined;
}

/** A filter from a query string; anything unknown or invalid is ignored, never thrown on. */
export function documentFilterFromParams(input: URLSearchParams | string): DocumentFilter {
	const params = typeof input === 'string' ? new URLSearchParams(input) : input;
	const first = (name: string) => params.get(name) ?? undefined;
	const linked = first('linked');
	return normalizeDocumentFilter({
		provider: params.getAll('provider'),
		from: first('from'),
		to: first('to'),
		amount_min: integer(first('amount_min')),
		amount_max: integer(first('amount_max')),
		currency: first('currency'),
		q: first('q') ?? '',
		linked: linked === 'true' ? true : linked === 'false' ? false : undefined
	});
}

/** No filter at all. */
export function isEmptyDocumentFilter(filter: DocumentFilter): boolean {
	return documentFilterKey(filter) === '';
}

export type DocumentFilterKey = 'provider' | 'date' | 'amount' | 'linked' | 'text';
export type DocumentFilterPart = { key: DocumentFilterKey; label: string };

/** The active parts of a filter in words, in a fixed order: the chip labels and the empty state. */
export function describeDocumentFilter(
	filter: DocumentFilter,
	locale: string
): DocumentFilterPart[] {
	const parts: DocumentFilterPart[] = [];
	const add = (key: DocumentFilterKey, label: string) => parts.push({ key, label });

	if (filter.provider.length === 1) add('provider', filter.provider[0]);
	else if (filter.provider.length > 1) add('provider', `${filter.provider.length} providers`);

	if (filter.from && filter.to) add('date', formatDateRange(filter.from, filter.to, locale));
	else if (filter.from) add('date', `From ${formatDate(filter.from, locale)}`);
	else if (filter.to) add('date', `Until ${formatDate(filter.to, locale)}`);

	const { amount_min: min, amount_max: max, currency } = filter;
	if (currency && (min !== undefined || max !== undefined)) {
		const money = (minor: number) => formatMoney(minor, currency, { locale, showPlus: false });
		const range =
			min !== undefined && max !== undefined
				? `${money(min)}–${money(max)}`
				: min !== undefined
					? `≥ ${money(min)}`
					: `≤ ${money(max!)}`;
		add('amount', `${range} ${currency}`);
	}

	if (filter.linked === false) add('linked', 'Not linked');
	else if (filter.linked === true) add('linked', 'Linked');
	if (filter.q) add('text', `“${filter.q}”`);
	return parts;
}
