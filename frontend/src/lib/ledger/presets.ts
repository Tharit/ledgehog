// The date ranges the date chip offers, computed from the household's today. Plain calendar
// arithmetic on `YYYY-MM-DD` strings; both ends are inclusive (patterns §3).

import type { IsoDate } from '#lib/types/domain.js';

export type DatePreset = { id: string; label: string; from: IsoDate; to: IsoDate };

/** The ISO date of a UTC calendar position; day 0 is the last day of the month before. */
function iso(year: number, monthIndex: number, day: number): IsoDate {
	return new Date(Date.UTC(year, monthIndex, day)).toISOString().slice(0, 10);
}

export function datePresets(today: IsoDate): DatePreset[] {
	const [year, month, day] = today.split('-').map(Number);
	const m = month - 1;
	return [
		{ id: 'this-month', label: 'This month', from: iso(year, m, 1), to: iso(year, m + 1, 0) },
		{ id: 'last-month', label: 'Last month', from: iso(year, m - 1, 1), to: iso(year, m, 0) },
		{ id: 'last-30-days', label: 'Last 30 days', from: iso(year, m, day - 29), to: today },
		// the twelve complete months before this one: the Overview's "last 12 months" (spec §8)
		{
			id: 'last-12-months',
			label: 'Last 12 months',
			from: iso(year, m - 12, 1),
			to: iso(year, m, 0)
		},
		{ id: 'this-year', label: 'This year', from: iso(year, 0, 1), to: iso(year, 11, 31) },
		{ id: 'last-year', label: 'Last year', from: iso(year - 1, 0, 1), to: iso(year - 1, 11, 31) }
	];
}

const DAY_MS = 86_400_000;

function parts(date: IsoDate): [number, number, number] {
	const [year, month, day] = date.split('-').map(Number);
	return [year, month - 1, day];
}

/**
 * The span before (`-1`) or after (`1`) a period, of the same length (reports.md): by calendar
 * months when the period is whole months (a month, a quarter, a year), by its days otherwise.
 */
export function stepRange(from: IsoDate, to: IsoDate, direction: -1 | 1): [IsoDate, IsoDate] {
	const [fy, fm, fd] = parts(from);
	const [ty, tm, td] = parts(to);
	if (fd === 1 && td === new Date(Date.UTC(ty, tm + 1, 0)).getUTCDate()) {
		const months = (ty - fy) * 12 + (tm - fm) + 1;
		const shift = direction * months;
		return [iso(fy, fm + shift, 1), iso(ty, tm + shift + 1, 0)];
	}
	const days = Math.round((Date.UTC(ty, tm, td) - Date.UTC(fy, fm, fd)) / DAY_MS) + 1;
	const shift = direction * days;
	return [iso(fy, fm, fd + shift), iso(ty, tm, td + shift)];
}
