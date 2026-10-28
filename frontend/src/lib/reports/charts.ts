// What the report charts draw, from the answers (design §8): plain data rows and series, so the
// mapping is tested without a chart. A chart is never the only place a figure is: every one has
// its table beside it, built from the same answers.
import { formatDate, formatDateRange, formatMonth, formatPointLabel } from '#lib/format/index.js';
import { measureLook } from '#lib/theme/measures.js';
import { resolveAccount, resolveCategory } from '#lib/theme/resolve.js';
import type { Account, Category } from '#lib/types/domain.js';
import type { Balances, CategorySeries, OverTime, Period, Savings, Step } from './shapes.js';
import type { ByCategory, Line } from './types.js';

/** The colour of "Other" in every chart (design §8), and its lead tile's icon (design §6). */
export const OTHER_COLOR = 'stone';
export const OTHER_ICON = 'circle-ellipsis';

export const minorOf = (line: Line): number | null => line.total?.amount ?? null;

function lastDayOfMonth(year: number, month: number): number {
	return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** A period the range cuts is a part of a month, quarter or year (spec §8). */
export function isWholePeriod(period: Period, step: Step): boolean {
	const [fy, fm, fd] = period.from.split('-').map(Number);
	const [ty, tm, td] = period.to.split('-').map(Number);
	if (fd !== 1) return false;
	if (step === 'month') return fy === ty && fm === tm && td === lastDayOfMonth(ty, tm);
	if (step === 'quarter') {
		return fy === ty && (fm - 1) % 3 === 0 && tm === fm + 2 && td === lastDayOfMonth(ty, tm);
	}
	return fy === ty && fm === 1 && tm === 12 && td === 31;
}

/** "Oct 2026", "Q4 2026", "2026"; a period the range cuts is labelled with its days. */
export function periodLabel(period: Period, step: Step, locale = 'en'): string {
	if (!isWholePeriod(period, step)) return formatDateRange(period.from, period.to, locale);
	const [year, month] = period.from.split('-').map(Number);
	if (step === 'month') return formatMonth(period.from, locale);
	if (step === 'quarter') return `Q${Math.floor((month - 1) / 3) + 1} ${year}`;
	return String(year);
}

// ---- the donut (By category)

export type Slice = {
	key: string;
	label: string;
	/** the magnitude drawn, in minor units */
	value: number;
	/** a dimension colour name */
	color: string;
	/** the lead tile's icon name (design §6) */
	icon: string;
	line: Line;
	/** null for "Other" */
	categoryId: number | null;
};

export type OppositeCategory = { categoryId: number; name: string; line: Line };

/**
 * The slices of the donut: the report's largest top-level categories and "Other" (stone). A
 * category whose net is of the opposite sign (refunds beyond purchases) is not a slice: it is
 * returned apart, to be named in a note.
 */
export function donutSlices(
	report: ByCategory,
	categories: ReadonlyMap<number, Category>
): { slices: Slice[]; opposite: OppositeCategory[] } {
	const slices: Slice[] = [];
	for (const slice of report.slices ?? []) {
		const value = Math.abs(minorOf(slice.total) ?? 0);
		if (value === 0) continue;
		const category = categories.get(slice.category_id);
		slices.push({
			key: `c${slice.category_id}`,
			label: category?.name ?? 'Category',
			value,
			color: resolveCategory(category, categories).color,
			icon: resolveCategory(category, categories).icon,
			line: slice.total,
			categoryId: slice.category_id
		});
	}
	const other = report.other;
	if (other && Math.abs(minorOf(other) ?? 0) > 0) {
		slices.push({
			key: 'other',
			label: 'Other',
			value: Math.abs(minorOf(other) ?? 0),
			color: OTHER_COLOR,
			icon: OTHER_ICON,
			line: other,
			categoryId: null
		});
	}
	const opposite = report.categories
		.filter((row) => row.parent_id === null && row.share_bp === null && row.total.total !== null)
		.map((row) => ({
			categoryId: row.category_id,
			name: categories.get(row.category_id)?.name ?? 'Category',
			line: row.total
		}));
	return { slices, opposite };
}

// ---- Over time: income and expense

export type IncomeExpensePoint = {
	key: string;
	label: string;
	/** above the zero line */
	income: number;
	/** below the zero line (zero or negative) */
	expense: number;
	/** null when the period's savings could not be valued */
	savings: number | null;
};

export function incomeExpensePoints(
	periods: readonly Period[],
	savings: readonly Savings[],
	step: Step,
	locale = 'en'
): IncomeExpensePoint[] {
	return periods.map((period, i) => ({
		key: period.from,
		label: periodLabel(period, step, locale),
		income: Math.max(0, minorOf(savings[i].income) ?? 0),
		expense: Math.min(0, minorOf(savings[i].expense) ?? 0),
		savings: minorOf(savings[i].savings)
	}));
}

// ---- Over time: by category

export type StackSeries = {
	key: string;
	label: string;
	color: string;
	/** the lead tile's icon name (design §6) */
	icon: string;
	categoryId: number | null;
};
export type StackRow = { key: string; label: string; [series: string]: string | number };

/**
 * Stacked bars of the top categories and "Other": one row per period, one value per series, the
 * magnitudes (the kind's sign is the axis's and the tooltip's).
 */
export function categoryStack(
	report: OverTime,
	categories: ReadonlyMap<number, Category>,
	locale = 'en'
): { series: StackSeries[]; rows: StackRow[] } {
	const byId = new Map<number, CategorySeries>(
		(report.categories ?? []).map((c) => [c.category_id, c])
	);
	const series: StackSeries[] = [];
	const values: Array<readonly Line[]> = [];
	for (const { category_id } of report.slices ?? []) {
		const source = byId.get(category_id);
		if (!source) continue;
		const category = categories.get(category_id);
		series.push({
			key: `c${category_id}`,
			label: category?.name ?? 'Category',
			color: resolveCategory(category, categories).color,
			icon: resolveCategory(category, categories).icon,
			categoryId: category_id
		});
		values.push(source.total);
	}
	if (report.other?.some((line) => (minorOf(line) ?? 0) !== 0)) {
		series.push({
			key: 'other',
			label: 'Other',
			color: OTHER_COLOR,
			icon: OTHER_ICON,
			categoryId: null
		});
		values.push(report.other);
	}
	const rows = report.periods.map((period, i) => {
		const row: StackRow = {
			key: period.from,
			label: periodLabel(period, report.step, locale)
		};
		series.forEach((s, j) => {
			row[s.key] = Math.abs(minorOf(values[j][i]) ?? 0);
		});
		return row;
	});
	return { series, rows };
}

// ---- Balances

function isMonthEnd(isoDate: string): boolean {
	const [y, m, d] = isoDate.split('-').map(Number);
	return d === lastDayOfMonth(y, m);
}

/** A point's label: "Oct 26" for a month-end; a point that is not one (today) is written as its date. */
export function pointColumnLabel(point: string, locale = 'en'): string {
	return isMonthEnd(point) ? formatPointLabel(point, locale) : formatDate(point, locale);
}

export type BalanceLine = {
	key: string;
	label: string;
	/** the line's colour: a dimension colour name, or `primary` for the net worth */
	color: string;
	/** the lead tile (design §6): the account's own, or the net worth measure's, stone */
	icon: string;
	tileColor: string;
	accountId: number | null;
};
export type BalanceRow = {
	key: string;
	date: Date;
	label: string;
	[series: string]: string | number | Date | null;
};

/**
 * The month-end points of the net worth (unless toggled off) and of the accounts toggled on, one
 * row per point. A balance that could not be valued is null: a gap, never a zero.
 */
export function balanceRows(
	report: Balances,
	accounts: ReadonlyMap<number, Account>,
	shown: ReadonlySet<number>,
	locale = 'en',
	netWorth = true
): { lines: BalanceLine[]; rows: BalanceRow[] } {
	const lines: BalanceLine[] = netWorth
		? [
				{
					key: 'net_worth',
					label: 'Net worth',
					color: 'primary',
					icon: measureLook('net_worth').icon,
					tileColor: measureLook('net_worth').color,
					accountId: null
				}
			]
		: [];
	const chosen = report.accounts.filter(
		(a) => shown.has(a.account_id) && a.balances.some((b) => b !== null)
	);
	for (const a of chosen) {
		const account = accounts.get(a.account_id);
		const look = account ? resolveAccount(account) : { icon: OTHER_ICON, color: OTHER_COLOR };
		lines.push({
			key: `a${a.account_id}`,
			label: account?.name ?? 'Account',
			color: look.color,
			icon: look.icon,
			tileColor: look.color,
			accountId: a.account_id
		});
	}
	const rows = report.points.map((point, i) => {
		const row: BalanceRow = {
			key: point,
			date: new Date(`${point}T00:00:00Z`),
			label: formatPointLabel(point, locale)
		};
		if (netWorth) row.net_worth = report.net_worth[i].total?.amount ?? null;
		for (const a of chosen) row[`a${a.account_id}`] = a.balances[i]?.amount ?? null;
		return row;
	});
	return { lines, rows };
}
