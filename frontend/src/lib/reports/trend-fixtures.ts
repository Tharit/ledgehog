// Test fixtures of the reports' answers beyond the Overview's: the category tree, the periods, the
// savings of each, the balances. Whole API objects with sensible defaults.
import { account, category } from '#lib/ledger/fixtures.js';
import { buildLookups, type Lookups } from '#lib/ledger/lookups.js';
import type { Balances, CategorySeries, OverTime, Period, Savings } from './shapes.js';
import { line } from './fixtures.js';
import type { ByCategory, Line } from './types.js';

/** Food (sage) with Groceries and Eating out beneath, Home (slate), Salary (income, forest). */
export function reportLookups(): Lookups {
	return buildLookups({
		categories: [
			category({ id: 1, name: 'Food', kind: 'expense', color: 'sage', sort_order: 1 }),
			category({ id: 2, name: 'Groceries', kind: 'expense', parent_id: 1, color: null }),
			category({ id: 3, name: 'Eating out', kind: 'expense', parent_id: 1, color: null }),
			category({ id: 4, name: 'Home', kind: 'expense', color: 'slate', sort_order: 2 }),
			category({ id: 5, name: 'Salary', kind: 'income', color: 'forest', sort_order: 3 }),
			category({ id: 6, name: 'Refunds', kind: 'expense', color: 'ochre', sort_order: 4 })
		],
		accounts: [
			account({ id: 1, name: 'Giro', kind: 'checking', color: 'forest' }),
			account({ id: 2, name: 'Savings', kind: 'savings', color: 'teal' }),
			account({ id: 3, name: 'Depot', kind: 'depot', color: 'plum' })
		]
	});
}

/** A report of October 2026: Food 400 (itself 100, Groceries 200, Eating out 100), Home 600. */
export function byCategoryTree(over: Partial<ByCategory> = {}): ByCategory {
	const row = (
		category_id: number,
		parent_id: number | null,
		own: Line,
		total: Line,
		share_bp: number | null
	) => ({ category_id, parent_id, own, total, share_bp });
	return {
		base_currency: 'EUR',
		from: '2026-10-01',
		to: '2026-10-31',
		kind: 'expense',
		total: line(-100000, { count: 12 }),
		categories: [
			row(4, null, line(-60000, { count: 4 }), line(-60000, { count: 4 }), 6000),
			row(1, null, line(-10000, { count: 1 }), line(-40000, { count: 8 }), 4000),
			row(2, 1, line(-20000, { count: 5 }), line(-20000, { count: 5 }), 2000),
			row(3, 1, line(-10000, { count: 2 }), line(-10000, { count: 2 }), 1000),
			row(6, null, line(500, { count: 1 }), line(500, { count: 1 }), null)
		],
		slices: [
			{ category_id: 4, total: line(-60000, { count: 4 }) },
			{ category_id: 1, total: line(-40000, { count: 8 }) }
		],
		other: line(-1000, { count: 1 }),
		unclassified_out: line(-2500, { count: 2 }),
		unclassified_in: line(0),
		reconciliations: line(100, { count: 1 }),
		unconfirmed_count: 3,
		...over
	};
}

export function period(from: string, to: string): Period {
	return { from, to };
}

export function savings(over: Partial<Savings> = {}): Savings {
	return {
		income: line(300000, { count: 2 }),
		expense: line(-120000, { count: 10 }),
		unclassified: line(-5000, { count: 1 }),
		reconciliations: line(0),
		savings: line(175000, { count: 13 }),
		rate_bp: 5833,
		incomplete: true,
		...over
	};
}

/** Two months (August whole, September cut at the 15th) of income and expense, and their total. */
export function overTimeSavings(over: Partial<OverTime> = {}): OverTime {
	return {
		base_currency: 'EUR',
		kind: 'expense',
		step: 'month',
		periods: [period('2026-08-01', '2026-08-31'), period('2026-09-01', '2026-09-15')],
		savings: [
			savings(),
			savings({
				income: line(0),
				expense: line(-40000),
				unclassified: line(0),
				savings: line(-40000),
				rate_bp: null,
				incomplete: false
			})
		],
		total: savings({
			income: line(300000),
			expense: line(-160000),
			unclassified: line(-5000),
			savings: line(135000),
			rate_bp: 4500
		}),
		...over
	};
}

function series(
	category_id: number,
	parent_id: number | null,
	own: number[],
	total: number[]
): CategorySeries {
	const lines = (values: number[]) => values.map((v) => line(v, { count: v === 0 ? 0 : 1 }));
	return {
		category_id,
		parent_id,
		own: lines(own),
		total: lines(total),
		sum: line(total.reduce((a, b) => a + b, 0))
	};
}

/** By category over two months: Home (-300, -300), Food (-100/-200 with its own 50 in August). */
export function overTimeCategories(over: Partial<OverTime> = {}): OverTime {
	return {
		base_currency: 'EUR',
		kind: 'expense',
		step: 'month',
		periods: [period('2026-08-01', '2026-08-31'), period('2026-09-01', '2026-09-30')],
		categories: [
			series(4, null, [-30000, -30000], [-30000, -30000]),
			series(1, null, [-5000, 0], [-10000, -20000]),
			series(2, 1, [-5000, -20000], [-5000, -20000])
		],
		slices: [{ category_id: 4 }, { category_id: 1 }],
		other: [line(0), line(-1500)],
		totals: [line(-40000), line(-51500)],
		sum: line(-91500),
		...over
	};
}

/** Balances at three month-ends (the last point is today): Giro, Savings and an unvalued Depot. */
export function balances(over: Partial<Balances> = {}): Balances {
	const money = (amount: number) => ({ amount, currency: 'EUR' });
	return {
		base_currency: 'EUR',
		points: ['2026-08-31', '2026-09-30', '2026-10-20'],
		net_worth: [
			{ total: money(500000), unvalued: [] },
			{ total: money(520000), unvalued: [] },
			{ total: money(530000), unvalued: [{ amount: money(0), accounts: 1 }] }
		],
		accounts: [
			{
				account_id: 1,
				balances: [money(100000), money(120000), money(130000)],
				native: [money(100000), money(120000), money(130000)]
			},
			{
				account_id: 2,
				balances: [money(400000), money(400000), money(400000)],
				native: [money(400000), money(400000), money(400000)]
			},
			{
				account_id: 3,
				balances: [null, null, null],
				native: [
					{ amount: 7000, currency: 'USD' },
					{ amount: 7500, currency: 'USD' },
					{ amount: 8000, currency: 'USD' }
				]
			}
		],
		...over
	};
}
