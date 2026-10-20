import { describe, expect, it } from 'vitest';
import {
	balanceRows,
	categoryStack,
	donutSlices,
	incomeExpensePoints,
	isWholePeriod,
	periodLabel,
	pointColumnLabel
} from './charts.js';
import { line } from './fixtures.js';
import {
	balances,
	byCategoryTree,
	overTimeCategories,
	overTimeSavings,
	period,
	reportLookups
} from './trend-fixtures.js';

const { categories, accounts } = reportLookups();

describe('periodLabel', () => {
	it('names a whole month, quarter and year', () => {
		expect(periodLabel(period('2026-08-01', '2026-08-31'), 'month')).toBe('Aug 2026');
		expect(periodLabel(period('2026-10-01', '2026-12-31'), 'quarter')).toBe('Q4 2026');
		expect(periodLabel(period('2026-01-01', '2026-12-31'), 'year')).toBe('2026');
	});

	it('labels a period the range cuts with its days', () => {
		expect(periodLabel(period('2026-09-01', '2026-09-15'), 'month')).toBe('Sep 1 – Sep 15');
		expect(isWholePeriod(period('2026-02-01', '2026-02-28'), 'month')).toBe(true);
		expect(isWholePeriod(period('2026-02-10', '2026-02-28'), 'month')).toBe(false);
		expect(isWholePeriod(period('2026-02-01', '2026-04-30'), 'quarter')).toBe(false);
		expect(isWholePeriod(period('2026-04-01', '2026-06-30'), 'quarter')).toBe(true);
	});
});

describe('donutSlices', () => {
	it('draws the largest categories by magnitude, then Other in stone', () => {
		const { slices } = donutSlices(byCategoryTree(), categories);

		expect(slices.map((s) => [s.label, s.value, s.color])).toEqual([
			['Home', 60000, 'slate'],
			['Food', 40000, 'sage'],
			['Other', 1000, 'stone']
		]);
		expect(slices[2].categoryId).toBeNull();
	});

	it('names the category whose net is of the other sign instead of drawing it', () => {
		const { slices, opposite } = donutSlices(byCategoryTree(), categories);

		expect(slices.map((s) => s.label)).not.toContain('Refunds');
		expect(opposite).toEqual([{ categoryId: 6, name: 'Refunds', line: line(500, { count: 1 }) }]);
	});

	it('has no Other when nothing remains, and skips a slice that could not be valued', () => {
		const { slices } = donutSlices(
			byCategoryTree({
				other: null,
				slices: [
					{ category_id: 4, total: line(null, { count: 2 }) },
					{ category_id: 1, total: line(-40000) }
				]
			}),
			categories
		);

		expect(slices.map((s) => s.label)).toEqual(['Food']);
	});
});

describe('incomeExpensePoints', () => {
	it('puts income above and expense below the zero line, with the savings', () => {
		const report = overTimeSavings();
		const points = incomeExpensePoints(report.periods, report.savings!, 'month');

		expect(points[0]).toMatchObject({
			label: 'Aug 2026',
			income: 300000,
			expense: -120000,
			savings: 175000
		});
		expect(points[1]).toMatchObject({ income: 0, expense: -40000, savings: -40000 });
	});

	it('leaves the savings of a period that could not be valued out of the line', () => {
		const report = overTimeSavings();
		report.savings![0] = { ...report.savings![0], savings: line(null, { count: 3 }) };

		expect(incomeExpensePoints(report.periods, report.savings!, 'month')[0].savings).toBeNull();
	});
});

describe('categoryStack', () => {
	it('is the top categories and Other, per period, in their colours', () => {
		const { series, rows } = categoryStack(overTimeCategories(), categories);

		expect(series.map((s) => [s.label, s.color])).toEqual([
			['Home', 'slate'],
			['Food', 'sage'],
			['Other', 'stone']
		]);
		expect(rows.map((r) => [r.label, r.c4, r.c1, r.other])).toEqual([
			['Aug 2026', 30000, 10000, 0],
			['Sep 2026', 30000, 20000, 1500]
		]);
	});

	it('has no Other series when nothing is in it', () => {
		const { series } = categoryStack(overTimeCategories({ other: [line(0), line(0)] }), categories);

		expect(series.map((s) => s.key)).toEqual(['c4', 'c1']);
	});
});

describe('balanceRows', () => {
	it('is the net worth, and the accounts toggled on in their colours', () => {
		const { lines, rows } = balanceRows(balances(), accounts, new Set([2]));

		expect(lines.map((l) => [l.label, l.color])).toEqual([
			['Net worth', 'primary'],
			['Savings', 'teal']
		]);
		expect(rows.map((r) => [r.key, r.net_worth, r.a2])).toEqual([
			['2026-08-31', 500000, 400000],
			['2026-09-30', 520000, 400000],
			['2026-10-20', 530000, 400000]
		]);
	});

	it('does not chart an account without a valued balance, even when toggled', () => {
		const { lines } = balanceRows(balances(), accounts, new Set([3]));

		expect(lines.map((l) => l.label)).toEqual(['Net worth']);
	});
});

describe('pointColumnLabel', () => {
	it('writes a month-end as its month and today as its date', () => {
		expect(pointColumnLabel('2026-09-30')).toBe('Sep 26');
		expect(pointColumnLabel('2026-10-20')).toBe('Oct 20, 2026');
	});
});
