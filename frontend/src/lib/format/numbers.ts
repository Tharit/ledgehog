/** A count ("1,234" or "1.234") in the locale's grouping. */
export function formatCount(count: number, locale = 'en'): string {
	return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(count);
}
