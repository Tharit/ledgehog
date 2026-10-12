// The filter in words: the label of each chip, and the active parts the empty state names.
import { formatDate, formatDateRange, formatMoney } from '#lib/format/index.js';
import type { EntryFilter } from '#lib/types/domain.js';
import type { Lookups } from './lookups.js';
import { REVIEW_FLAG_INFO } from './review.js';
import { ENTRY_TYPE_INFO } from './types.js';

export type FilterKey =
	'date' | 'account' | 'category' | 'payee' | 'tag' | 'amount' | 'flag' | 'type' | 'text';

export type FilterPart = { key: FilterKey; label: string };

function named(
	ids: readonly number[],
	names: ReadonlyMap<number, { name: string }>,
	fallback: string,
	plural: string
): string {
	if (ids.length === 1) return names.get(ids[0])?.name ?? `${fallback} ${ids[0]}`;
	return `${ids.length} ${plural}`;
}

function amountLabel(filter: EntryFilter, locale: string): string {
	const pieces: string[] = [];
	if (filter.direction) pieces.push(filter.direction === 'out' ? 'Out' : 'In');
	const currency = filter.currency;
	const money = (minor: number) =>
		currency ? formatMoney(minor, currency, { locale, showPlus: false }) : String(minor);
	const { amount_min: min, amount_max: max } = filter;
	let range = '';
	if (min !== undefined && max !== undefined) range = `${money(min)}–${money(max)}`;
	else if (min !== undefined) range = `≥ ${money(min)}`;
	else if (max !== undefined) range = `≤ ${money(max)}`;
	if (range) pieces.push(currency ? `${range} ${currency}` : range);
	else if (currency) pieces.push(currency);
	return pieces.join(' · ');
}

/** The active parts of a filter, in a fixed order; nothing for a dimension that is not set. */
export function describeFilter(
	filter: EntryFilter,
	{ lookups, locale }: { lookups: Lookups; locale: string }
): FilterPart[] {
	const parts: FilterPart[] = [];
	const add = (key: FilterKey, label: string) => parts.push({ key, label });

	if (filter.from && filter.to) add('date', formatDateRange(filter.from, filter.to, locale));
	else if (filter.from) add('date', `From ${formatDate(filter.from, locale)}`);
	else if (filter.to) add('date', `Until ${formatDate(filter.to, locale)}`);

	if (filter.account_id.length) {
		add('account', named(filter.account_id, lookups.accounts, 'Account', 'accounts'));
	}

	if (filter.category_id.length || filter.uncategorised) {
		let label = filter.category_id.length
			? named(filter.category_id, lookups.categories, 'Category', 'categories')
			: '';
		if (filter.uncategorised) label = label ? `${label} + uncategorised` : 'Uncategorised';
		if (filter.category_id.length && !filter.category_descendants) label += ' (exact)';
		add('category', label);
	}

	if (filter.payee_id.length)
		add('payee', named(filter.payee_id, lookups.payees, 'Payee', 'payees'));
	if (filter.tag_id.length) add('tag', named(filter.tag_id, lookups.tags, 'Tag', 'tags'));

	const amount = amountLabel(filter, locale);
	if (amount) add('amount', amount);

	if (filter.flag.length) {
		add(
			'flag',
			filter.flag.length === 1
				? (REVIEW_FLAG_INFO[filter.flag[0]]?.name ?? filter.flag[0])
				: `${filter.flag.length} review flags`
		);
	}

	if (filter.type.length) {
		add('type', `Type: ${filter.type.map((t) => ENTRY_TYPE_INFO[t]?.name ?? t).join(', ')}`);
	}
	if (filter.q) add('text', `“${filter.q}”`);
	return parts;
}
