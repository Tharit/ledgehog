/** A savings rate (basis points) in whole percent ("63%"), "—" when there is none. */
export function formatRate(rateBp: number | null, locale = 'en'): string {
	if (rateBp === null) return '—';
	return new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(
		Math.round(rateBp / 100) / 100
	);
}

/** A count ("1,234" or "1.234") in the locale's grouping. */
export function formatCount(count: number, locale = 'en'): string {
	return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(count);
}
