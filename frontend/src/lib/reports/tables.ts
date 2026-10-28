// The tables beside the charts (reports.md: "every chart has its table beside it as the readable
// data"), as plain models the components draw: rows, cells, and the link every number carries.
import { formatMoney } from '#lib/format/index.js';
import { ACCOUNT_KINDS } from '#lib/accounts/kinds.js';
import { type Measure } from '#lib/theme/measures.js';
import type { Account, Category } from '#lib/types/domain.js';
import { minorOf, periodLabel } from './charts.js';
import {
	categoryHref,
	kindHref,
	reconciliationsHref,
	unclassifiedHref,
	unconfirmedHref,
	type Scope
} from './links.js';
import type { Balances, OverTime, Period, Savings } from './shapes.js';
import type { ByCategory, Line } from './types.js';

// ---- the category tree

/** One row of a category tree: a category, or "Name (itself)" under a parent that has entries of its own. */
export type TreeRow = {
	key: string;
	categoryId: number;
	name: string;
	depth: number;
	itself: boolean;
	hasChildren: boolean;
};

type TreeNode = { category_id: number; parent_id: number | null; own: Line };

/**
 * The rows of a flat, depth-first list of categories (the server's order). A parent that has
 * entries of its own gets a child row "Name (itself)" first, so a row's amount is always the sum
 * of its children.
 */
export function treeRows(
	nodes: readonly TreeNode[],
	categories: ReadonlyMap<number, Category>
): TreeRow[] {
	const present = new Set(nodes.map((n) => n.category_id));
	const children = new Map<number, number>();
	for (const n of nodes) {
		if (n.parent_id !== null && present.has(n.parent_id)) {
			children.set(n.parent_id, (children.get(n.parent_id) ?? 0) + 1);
		}
	}
	const depths = new Map<number, number>();
	const rows: TreeRow[] = [];
	for (const n of nodes) {
		const depth =
			n.parent_id !== null && depths.has(n.parent_id) ? (depths.get(n.parent_id) as number) + 1 : 0;
		depths.set(n.category_id, depth);
		const name = categories.get(n.category_id)?.name ?? 'Category';
		const hasChildren = (children.get(n.category_id) ?? 0) > 0;
		rows.push({
			key: `c${n.category_id}`,
			categoryId: n.category_id,
			name,
			depth,
			itself: false,
			hasChildren
		});
		if (hasChildren && n.own.count > 0) {
			rows.push({
				key: `c${n.category_id}-itself`,
				categoryId: n.category_id,
				name: `${name} (itself)`,
				depth: depth + 1,
				itself: true,
				hasChildren: false
			});
		}
	}
	return rows;
}

// ---- By category

export type CategoryTableRow = TreeRow & {
	line: Line;
	/** of the kind's total, basis points; null for a net of the other sign */
	shareBp: number | null;
	/** 0 to 1: the row's magnitude against the kind's total, for the thin bar */
	bar: number;
	href: string;
};

function ratio(line: Line, whole: Line): number {
	const a = Math.abs(minorOf(line) ?? 0);
	const b = Math.abs(minorOf(whole) ?? 0);
	return b === 0 ? 0 : Math.min(1, a / b);
}

function shareOf(line: Line, whole: Line): number | null {
	const a = minorOf(line);
	const b = minorOf(whole);
	if (a === null || b === null || b === 0 || Math.sign(a) !== Math.sign(b)) return null;
	return Math.round((a * 10000) / b);
}

export function categoryTable(
	report: ByCategory,
	categories: ReadonlyMap<number, Category>,
	scope: Scope
): CategoryTableRow[] {
	const byId = new Map(report.categories.map((r) => [r.category_id, r]));
	return treeRows(report.categories, categories).map((row) => {
		const source = byId.get(row.categoryId)!;
		const line = row.itself ? source.own : source.total;
		return {
			...row,
			line,
			shareBp: row.itself ? shareOf(line, report.total) : source.share_bp,
			bar: ratio(line, report.total),
			href: categoryHref(scope, row.categoryId, row.itself)
		};
	});
}

export type SideLine = {
	key: string;
	label: string;
	/** the measure whose lead tile the row takes */
	measure: Measure;
	line: Line;
	href: string;
	explanation: string;
};

/** "Not in the categories above": what stands beside the tree, and the entries not yet confirmed. */
export function notInCategories(
	report: ByCategory,
	scope: Scope
): { lines: SideLine[]; unconfirmed: { count: number; href: string } } {
	return {
		lines: [
			{
				key: 'unclassified-out',
				measure: 'unclassified',
				label: 'Unclassified, out',
				line: report.unclassified_out,
				href: unclassifiedHref(scope, 'out'),
				explanation: 'Money out that has no category yet.'
			},
			{
				key: 'unclassified-in',
				measure: 'unclassified',
				label: 'Unclassified, in',
				line: report.unclassified_in,
				href: unclassifiedHref(scope, 'in'),
				explanation: 'Money in that has no category yet.'
			},
			{
				key: 'reconciliations',
				measure: 'reconciliations',
				label: 'Reconciliations',
				line: report.reconciliations,
				href: reconciliationsHref(scope),
				explanation: 'What the entries do not explain of a balance.'
			}
		],
		unconfirmed: { count: report.unconfirmed_count, href: unconfirmedHref(scope) }
	};
}

// ---- Over time

export type Column = { key: string; label: string };

export type TrendCell =
	| { kind: 'line'; line: Line; href?: string; title?: string }
	| { kind: 'rate'; bp: number | null; incomplete: boolean; title: string };

export type TrendRow = {
	key: string;
	label: string;
	/** the measure whose lead tile the row takes */
	measure: Measure;
	strong?: boolean;
	cells: TrendCell[];
};

function periodScope(period: Period, scope: Scope): Scope {
	return { ...scope, from: period.from, to: period.to };
}

const SAVINGS_TITLE = 'Income + Expense + Unclassified + Reconciliations';
const RATE_TITLE = 'Savings ÷ Income';

/**
 * *Income and expense*: the rows Income, Expense, Unclassified, Reconciliations, Savings and
 * Savings rate, so each column visibly sums to its savings, and a Total column. Savings and the
 * rate are derived figures: not links, their tooltip names the components.
 */
export function savingsTable(
	report: OverTime,
	categories: ReadonlyMap<number, Category>,
	scope: Scope,
	locale = 'en'
): { columns: Column[]; rows: TrendRow[] } {
	const steps: { savings: Savings; scope: Scope }[] = [
		...report.periods.map((period, i) => ({
			savings: (report.savings ?? [])[i],
			scope: periodScope(period, scope)
		})),
		{ savings: report.total as Savings, scope }
	];
	const columns: Column[] = [
		...report.periods.map((p) => ({ key: p.from, label: periodLabel(p, report.step, locale) })),
		{ key: 'total', label: 'Total' }
	];
	const line = (pick: (s: Savings) => Line, href?: (s: Scope) => string, title?: string) =>
		steps.map((s): TrendCell => ({
			kind: 'line',
			line: pick(s.savings),
			href: href?.(s.scope),
			title
		}));
	const rows: TrendRow[] = [
		{
			key: 'income',
			measure: 'income',
			label: 'Income',
			cells: line(
				(s) => s.income,
				(sc) => kindHref(sc, 'income', categories)
			)
		},
		{
			key: 'expense',
			measure: 'expense',
			label: 'Expense',
			cells: line(
				(s) => s.expense,
				(sc) => kindHref(sc, 'expense', categories)
			)
		},
		{
			key: 'unclassified',
			measure: 'unclassified',
			label: 'Unclassified',
			cells: line(
				(s) => s.unclassified,
				(sc) => unclassifiedHref(sc)
			)
		},
		{
			key: 'reconciliations',
			measure: 'reconciliations',
			label: 'Reconciliations',
			cells: line(
				(s) => s.reconciliations,
				(sc) => reconciliationsHref(sc)
			)
		},
		{
			key: 'savings',
			measure: 'savings',
			label: 'Savings',
			strong: true,
			cells: line((s) => s.savings, undefined, SAVINGS_TITLE)
		},
		{
			key: 'rate',
			measure: 'savings_rate',
			label: 'Savings rate',
			cells: steps.map((s): TrendCell => ({
				kind: 'rate',
				bp: s.savings.rate_bp,
				incomplete: s.savings.incomplete,
				title: RATE_TITLE
			}))
		}
	];
	return { columns, rows };
}

export type CategoryTrendRow = TreeRow & { cells: { line: Line; href: string }[] };

/**
 * *By category*: the tree with a column per period and a total, each cell drilling into the
 * ledger for its period; and the kind's total beneath.
 */
export function categoryTrendTable(
	report: OverTime,
	categories: ReadonlyMap<number, Category>,
	scope: Scope,
	locale = 'en'
): { columns: Column[]; rows: CategoryTrendRow[]; total: TrendRow } {
	const list = report.categories ?? [];
	const byId = new Map(list.map((c) => [c.category_id, c]));
	const scopes = [...report.periods.map((p) => periodScope(p, scope)), scope];
	const columns: Column[] = [
		...report.periods.map((p) => ({ key: p.from, label: periodLabel(p, report.step, locale) })),
		{ key: 'total', label: 'Total' }
	];
	const rows = treeRows(
		list.map((c) => ({
			category_id: c.category_id,
			parent_id: c.parent_id,
			own: c.own_sum
		})),
		categories
	).map((row) => {
		const source = byId.get(row.categoryId)!;
		const lines = row.itself ? [...source.own, source.own_sum] : [...source.total, source.sum];
		return {
			...row,
			cells: lines.map((line, i) => ({
				line,
				href: categoryHref(scopes[i], row.categoryId, row.itself)
			}))
		};
	});
	const totals = [...(report.totals ?? []), report.sum as Line];
	const kind = report.kind;
	return {
		columns,
		rows,
		total: {
			key: 'total',
			measure: kind,
			label: 'Total',
			strong: true,
			cells: totals.map((line, i): TrendCell => ({
				kind: 'line',
				line,
				href: kindHref(scopes[i], kind, categories)
			}))
		}
	};
}

// ---- Balances

export type BalanceCell = {
	minor: number | null;
	/** the currency of `minor` */
	currency: string;
	/** why there is no figure, or what it leaves out */
	note?: string;
};

export type BalanceTableRow = {
	key: string;
	label: string;
	/** set on the net-worth row, which is read by a measure rather than an account */
	measure?: Measure;
	accountId: number | null;
	cells: BalanceCell[];
};
/** A kind: the net worth of its accounts (the server's) against the month-ends, its accounts beneath. */
export type BalanceGroup = {
	key: string;
	label: string;
	cells: BalanceCell[];
	rows: BalanceTableRow[];
};

/** A net worth at a point, as the table shows it: the figure, or what it leaves out. */
function netWorthCells(points: Balances['net_worth'], currency: string): BalanceCell[] {
	return points.map((p) => ({
		minor: p.total?.amount ?? null,
		currency,
		note:
			p.total === null
				? 'No balance could be valued.'
				: p.unvalued.length > 0
					? `${p.unvalued.reduce((n, u) => n + u.accounts, 0)} account(s) could not be valued and are not in it.`
					: undefined
	}));
}

/**
 * The lines against the month-ends: net worth, then each kind with the net worth of its accounts
 * and the accounts beneath it. An account with no valued balance at any point is not in the
 * table: it is listed as unvalued.
 */
export function balanceTable(
	report: Balances,
	accounts: ReadonlyMap<number, Account>,
	locale = 'en'
): {
	net: BalanceTableRow;
	groups: BalanceGroup[];
	unvalued: { accountId: number; name: string; native: string }[];
} {
	const base = report.base_currency;
	const net: BalanceTableRow = {
		key: 'net-worth',
		label: 'Net worth',
		measure: 'net_worth',
		accountId: null,
		cells: netWorthCells(report.net_worth, base)
	};
	const unvalued: { accountId: number; name: string; native: string }[] = [];
	const byKind = new Map<string, BalanceTableRow[]>();
	for (const a of report.accounts) {
		const account = accounts.get(a.account_id);
		const name = account?.name ?? 'Account';
		const everyNull = a.balances.every((b) => b === null);
		if (everyNull && a.native.some((n) => n.amount !== 0)) {
			const last = a.native[a.native.length - 1];
			unvalued.push({
				accountId: a.account_id,
				name,
				native: formatMoney(last.amount, last.currency, {
					locale,
					showCurrency: true,
					showPlus: false
				})
			});
			continue;
		}
		const row: BalanceTableRow = {
			key: `a${a.account_id}`,
			label: name,
			accountId: a.account_id,
			cells: a.balances.map((b, i) => ({
				minor: b?.amount ?? null,
				currency: base,
				note:
					b === null && a.native[i].amount !== 0
						? `Not valued: ${formatMoney(a.native[i].amount, a.native[i].currency, { locale, showCurrency: true, showPlus: false })}`
						: undefined
			}))
		};
		const kind = account?.kind ?? 'asset';
		byKind.set(kind, [...(byKind.get(kind) ?? []), row]);
	}
	const labels = new Map(ACCOUNT_KINDS.map(({ kind, label }) => [kind, label]));
	const groups = report.kinds.map(({ kind, net_worth }) => ({
		key: kind,
		label: labels.get(kind) ?? kind,
		cells: netWorthCells(net_worth, base),
		rows: byKind.get(kind) ?? []
	}));
	return { net, groups, unvalued };
}
