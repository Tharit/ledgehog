// How the report charts write their axes (design §8): month-ends and compact amounts. Locale
// formatting lives here (architecture §6.6).
import { minorUnitDigits } from './money.js';

/** A month-end for an axis: "Oct 26". */
export function formatPointLabel(isoDate: string, locale = 'en'): string {
	return new Intl.DateTimeFormat(locale, {
		month: 'short',
		year: '2-digit',
		timeZone: 'UTC'
	}).format(new Date(`${isoDate}T00:00:00Z`));
}

/** An axis tick: the amount in major units, compact ("1.2K"). The sign is the caller's. */
export function formatCompactAmount(minor: number, currency: string, locale = 'en'): string {
	const value = minor / 10 ** minorUnitDigits(currency);
	return new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(
		value
	);
}
