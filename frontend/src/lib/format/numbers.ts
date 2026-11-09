/** A savings rate (basis points) in whole percent ("63%"), "—" when there is none. */
export function formatRate(rateBp: number | null, locale = 'en'): string {
	if (rateBp === null) return '—';
	return new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(
		Math.round(rateBp / 100) / 100
	);
}

/** An annual return in basis points as a signed percent with one decimal: 623 is "+6.2 %"; null is "—". */
export function formatReturn(rateBp: number | null, locale = 'en'): string {
	if (rateBp === null) return '—';
	const tenths = Math.round(rateBp / 10);
	const text = new Intl.NumberFormat(locale, {
		minimumFractionDigits: 1,
		maximumFractionDigits: 1
	}).format(Math.abs(tenths) / 10);
	const sign = tenths < 0 ? '\u2212' : tenths > 0 ? '+' : '';
	return `${sign}${text}\u00a0%`;
}

/** A count ("1,234" or "1.234") in the locale's grouping. */
export function formatCount(count: number, locale = 'en'): string {
	return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(count);
}
