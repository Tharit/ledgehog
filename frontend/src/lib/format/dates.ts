// Dates and instants (architecture §4.5, §6.6, patterns §3).
//
// A domain date (booked_on, a balance date) is a calendar date, `YYYY-MM-DD`. It is never turned
// into a local-time Date: the parts are read from the string and formatted in UTC, so no time
// zone can move it by a day.

/** A calendar date as the API sends it. */
export type IsoDate = string;

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const EN_DASH = '\u2013';
const MS_PER_DAY = 86_400_000;

function utcDate(isoDate: IsoDate): Date {
	const match = ISO_DATE.exec(isoDate);
	if (!match) throw new RangeError(`not a calendar date: ${isoDate}`);
	const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
	const date = new Date(Date.UTC(year, month - 1, day));
	if (date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) {
		throw new RangeError(`not a calendar date: ${isoDate}`);
	}
	return date;
}

/** A calendar date in the locale's medium format ("11.10.2026"). */
export function formatDate(isoDate: IsoDate, locale = 'en'): string {
	const format = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' });
	return format.format(utcDate(isoDate));
}

/** A calendar date written out in full ("Sunday, October 11, 2026"), for a page's date line. */
export function formatLongDate(isoDate: IsoDate, locale = 'en'): string {
	const format = new Intl.DateTimeFormat(locale, { dateStyle: 'full', timeZone: 'UTC' });
	return format.format(utcDate(isoDate));
}

/** An instant (a run's start, a session) in the household's zone, with date and time. */
export function formatInstant(iso: string, timeZone: string, locale = 'en'): string {
	const instant = new Date(iso);
	if (Number.isNaN(instant.getTime())) throw new RangeError(`not an instant: ${iso}`);
	const format = new Intl.DateTimeFormat(locale, {
		dateStyle: 'medium',
		timeStyle: 'short',
		timeZone
	});
	return format.format(instant);
}

/** The time of day of an instant in the household's zone ("14:32"), for a deadline today. */
export function formatTime(iso: string, timeZone: string, locale = 'en'): string {
	const instant = new Date(iso);
	if (Number.isNaN(instant.getTime())) throw new RangeError(`not an instant: ${iso}`);
	return new Intl.DateTimeFormat(locale, { timeStyle: 'short', timeZone }).format(instant);
}

/** Today's calendar date in the household's zone. */
export function todayIso(timeZone: string, now: Date = new Date()): IsoDate {
	const parts = new Intl.DateTimeFormat('en-CA', {
		year: 'numeric',
		month: '2-digit',
		day: '2-digit',
		timeZone
	}).formatToParts(now);
	const part = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
	return `${part('year')}-${part('month')}-${part('day')}`;
}

/**
 * "3 days ago", "yesterday" for a calendar date, counted from `today` (the household's day).
 * The absolute date goes in `title`, for a tooltip (patterns §3).
 */
export function relativeDay(
	isoDate: IsoDate,
	today: IsoDate,
	locale = 'en'
): { text: string; title: string } {
	const days = Math.round((utcDate(isoDate).getTime() - utcDate(today).getTime()) / MS_PER_DAY);
	return {
		text: new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }).format(days, 'day'),
		title: formatDate(isoDate, locale)
	};
}

/**
 * An inclusive range ("1 Mar – 31 Mar"). The year is written only when the range spans two years.
 */
export function formatDateRange(from: IsoDate, to: IsoDate, locale = 'en'): string {
	const start = utcDate(from);
	const end = utcDate(to);
	const withYear = start.getUTCFullYear() !== end.getUTCFullYear();
	const format = new Intl.DateTimeFormat(locale, {
		day: 'numeric',
		month: 'short',
		year: withYear ? 'numeric' : undefined,
		timeZone: 'UTC'
	});
	if (from === to) return format.format(start);
	return `${format.format(start)} ${EN_DASH} ${format.format(end)}`;
}

/** The month of a calendar date spelled out ("October"). */
export function formatMonthName(isoDate: IsoDate, locale = 'en'): string {
	const format = new Intl.DateTimeFormat(locale, { month: 'long', timeZone: 'UTC' });
	return format.format(utcDate(isoDate));
}

/** The month of a calendar date ("Mar 2026"), for evidence that spans time. */
export function formatMonth(isoDate: IsoDate, locale = 'en'): string {
	const format = new Intl.DateTimeFormat(locale, {
		month: 'short',
		year: 'numeric',
		timeZone: 'UTC'
	});
	return format.format(utcDate(isoDate));
}
