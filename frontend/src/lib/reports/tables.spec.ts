import { describe, expect, it } from 'vitest';
import { line } from './fixtures.js';
import type { Scope } from './links.js';
import {
	accountTable,
	balanceTable,
	categoryTable,
	categoryTrendTable,
	notInCategories,
	savingsTable
} from './tables.js';
import {
	balances,
	byAccount,
	byAccountLookups,
	byCategoryTree,
	overTimeCategories,
	overTimeSavings,
	reportLookups
} from './trend-fixtures.js';

const { categories, accounts } = reportLookups();
const scope: Scope = { from: '2026-10-01', to: '2026-10-31', accountIds: [], tagIds: [] };

describe('categoryTable', () => {
	const rows = categoryTable(byCategoryTree(), categories, scope);

	it('is the tree depth-first with a parent that has entries of its own giving a "(itself)" row', () => {
		expect(rows.map((r) => [r.name, r.depth, r.itself])).toEqual([
			['Home', 0, false],
			['Food', 0, false],
			['Food (itself)', 1, true],
			['Groceries', 1, false],
			['Eating out', 1, false],
			['Refunds', 0, false]
		]);
	});

	it('gives each row its entries, amount, share and bar', () => {
		const food = rows.find((r) => r.name === 'Food')!;
		const itself = rows.find((r) => r.itself)!;

		expect(food.line.count).toBe(8);
		expect(food.shareBp).toBe(4000);
		expect(food.bar).toBeCloseTo(0.4);
		expect(itself.line.total?.amount).toBe(-10000);
		expect(itself.shareBp).toBe(1000);
		// a net of the other sign has no share
		expect(rows.find((r) => r.name === 'Refunds')!.shareBp).toBeNull();
	});

	it('links every amount to the ledger: the category with its descendants, "(itself)" exactly', () => {
		expect(rows.find((r) => r.name === 'Food')!.href).toBe(
			'/ledger?from=2026-10-01&to=2026-10-31&category_id=1'
		);
		expect(rows.find((r) => r.itself)!.href).toBe(
			'/ledger?from=2026-10-01&to=2026-10-31&category_id=1&category_descendants=false'
		);
	});
});

describe('notInCategories', () => {
	it('lists unclassified out and in, reconciliations and the unconfirmed count, each linked', () => {
		const side = notInCategories(byCategoryTree(), scope);

		expect(side.lines.map((l) => [l.key, l.href])).toEqual([
			[
				'unclassified-out',
				'/ledger?from=2026-10-01&to=2026-10-31&uncategorised=true&direction=out'
			],
			['unclassified-in', '/ledger?from=2026-10-01&to=2026-10-31&uncategorised=true&direction=in'],
			['reconciliations', '/ledger?from=2026-10-01&to=2026-10-31&type=reconciliation']
		]);
		expect(side.lines.map((l) => l.measure)).toEqual([
			'unclassified',
			'unclassified',
			'reconciliations'
		]);
		expect(side.unconfirmed).toEqual({
			count: 3,
			href: '/ledger?from=2026-10-01&to=2026-10-31&flag=unconfirmed'
		});
	});
});

describe('savingsTable', () => {
	const table = savingsTable(overTimeSavings(), categories, scope);

	it('carries each row’s measure, not left to its label', () => {
		expect(table.rows.map((r) => r.measure)).toEqual([
			'income',
			'expense',
			'unclassified',
			'reconciliations',
			'savings',
			'savings_rate'
		]);
	});

	it('has the rows in order and a column per period and a Total', () => {
		expect(table.columns.map((c) => c.label)).toEqual(['Aug 2026', 'Sep 1 – Sep 15', 'Total']);
		expect(table.rows.map((r) => r.key)).toEqual([
			'income',
			'expense',
			'unclassified',
			'reconciliations',
			'savings',
			'rate'
		]);
	});

	it('links income and expense with the period and the top-level categories of the kind', () => {
		const income = table.rows[0].cells;
		const expense = table.rows[1].cells;

		expect(income[0]).toMatchObject({
			href: '/ledger?from=2026-08-01&to=2026-08-31&category_id=5'
		});
		expect(expense[1]).toMatchObject({
			href: '/ledger?from=2026-09-01&to=2026-09-15&category_id=1&category_id=4&category_id=6'
		});
		// the Total column is the whole range
		expect(expense[2]).toMatchObject({
			href: '/ledger?from=2026-10-01&to=2026-10-31&category_id=1&category_id=4&category_id=6'
		});
	});

	it('links unclassified and reconciliations to the ledger filters for them', () => {
		expect(table.rows[2].cells[0]).toMatchObject({
			href: '/ledger?from=2026-08-01&to=2026-08-31&uncategorised=true'
		});
		expect(table.rows[3].cells[0]).toMatchObject({
			href: '/ledger?from=2026-08-01&to=2026-08-31&type=reconciliation'
		});
	});

	it('does not link the savings or the rate, and names their components', () => {
		for (const cell of table.rows[4].cells) {
			expect(cell).toMatchObject({ kind: 'line' });
			expect(cell).not.toHaveProperty('href', expect.any(String));
		}
		expect(table.rows[4].cells[0]).toMatchObject({
			title: 'Income + Expense + Unclassified + Reconciliations'
		});
		expect(table.rows[5].cells[0]).toMatchObject({
			kind: 'rate',
			bp: 5833,
			incomplete: true,
			title: 'Savings ÷ Income'
		});
		expect(table.rows[5].cells[1]).toMatchObject({ bp: null, incomplete: false });
	});

	it('carries the page filters onto every link', () => {
		const filtered = savingsTable(overTimeSavings(), categories, {
			...scope,
			accountIds: [2],
			tagIds: [7]
		});

		expect(filtered.rows[2].cells[0]).toMatchObject({
			href: '/ledger?from=2026-08-01&to=2026-08-31&account_id=2&uncategorised=true&tag_id=7'
		});
	});
});

describe('categoryTrendTable', () => {
	const table = categoryTrendTable(overTimeCategories(), categories, scope);

	it('is the tree with a cell per period and a total, "(itself)" rows included', () => {
		expect(table.rows.map((r) => r.name)).toEqual(['Home', 'Food', 'Food (itself)', 'Groceries']);
		const food = table.rows[1].cells.map((c) => c.line.total?.amount);
		expect(food).toEqual([-10000, -20000, -30000]);
		const itself = table.rows[2].cells.map((c) => c.line.total?.amount);
		expect(itself).toEqual([-5000, 0, -5000]);
	});

	it('drills each cell into the ledger for its category and period', () => {
		expect(table.rows[1].cells[0].href).toBe('/ledger?from=2026-08-01&to=2026-08-31&category_id=1');
		expect(table.rows[2].cells[1].href).toBe(
			'/ledger?from=2026-09-01&to=2026-09-30&category_id=1&category_descendants=false'
		);
		expect(table.rows[1].cells[2].href).toBe('/ledger?from=2026-10-01&to=2026-10-31&category_id=1');
	});

	it('ends in the kind total per period, read by the kind’s measure', () => {
		expect(table.total.measure).toBe('expense');
		expect(table.total.cells.map((c) => c.kind === 'line' && c.line.total?.amount)).toEqual([
			-40000, -51500, -91500
		]);
	});
});

describe('balanceTable', () => {
	const table = balanceTable(balances(), accounts);

	it('has the net worth and the valued accounts grouped by kind', () => {
		expect(table.net.cells.map((c) => c.minor)).toEqual([500000, 520000, 530000]);
		expect(table.groups.map((g) => [g.label, g.rows.map((r) => r.label)])).toEqual([
			['Checking', ['Giro']],
			['Savings', ['Savings']],
			['Depot', []]
		]);
	});

	it("gives each kind the server's net worth of its accounts, an unvalued kind with no figure", () => {
		expect(table.groups.map((g) => g.key)).toEqual(['checking', 'savings', 'depot']);
		expect(table.groups[0].cells.map((c) => c.minor)).toEqual([100000, 120000, 130000]);
		expect(table.groups[2].cells.map((c) => [c.minor, c.note])).toEqual([
			[null, 'No balance could be valued.'],
			[null, 'No balance could be valued.'],
			[null, 'No balance could be valued.']
		]);
		expect(table.groups[2].rows).toEqual([]);
	});

	it('reads the net worth row by its measure', () => {
		expect(table.net.measure).toBe('net_worth');
	});

	it('says what the net worth leaves out', () => {
		expect(table.net.cells[2].note).toBe('1 account(s) could not be valued and are not in it.');
		expect(table.net.cells[0].note).toBeUndefined();
	});

	it('lists an account with no valued balance as unvalued, in its own currency', () => {
		expect(table.unvalued).toEqual([{ accountId: 3, name: 'Depot', native: '80.00 USD' }]);
	});
});

describe('accountTable', () => {
	const lookups = byAccountLookups();
	const sections = accountTable(byAccount(), lookups.categories, lookups.accounts, {
		...scope,
		tagIds: [4]
	});
	const section = (key: string) => sections.find((s) => s.key === key)!;
	const row = (key: string) => sections.flatMap((s) => s.rows).find((r) => r.key === key)!;
	const query = (href: string | null) => new URLSearchParams(href!.split('?')[1]);

	it('has Income and Expense, Transfers, and "Not in the categories above"', () => {
		expect(sections.map((s) => s.label)).toEqual([
			'Income',
			'Expense',
			'Transfers',
			'Not in the categories above'
		]);
		expect(section('income').rows.map((r) => r.key)).toEqual([
			'income:c5',
			'income:c5:a1',
			'income:c7',
			'income:c7:a2',
			'income:total'
		]);
		// all the categories, not only the slices: Travel and Refunds are not slices
		expect(section('expense').rows.map((r) => r.key)).toEqual([
			'expense:c4',
			'expense:c4:a1',
			'expense:c4:a3',
			'expense:c1',
			'expense:c1:a1',
			'expense:c8',
			'expense:c8:a2',
			'expense:c6',
			'expense:c6:a1',
			'expense:total'
		]);
	});

	it('gives a category its By category figure and each account its link, as drill-downs', () => {
		const salary = row('income:c5');
		expect(salary).toMatchObject({ label: 'Salary', depth: 0, hasChildren: true, categoryId: 5 });
		expect(salary.line.total!.amount).toBe(300000);
		expect(Object.fromEntries(query(salary.href))).toEqual({
			from: '2026-10-01',
			to: '2026-10-31',
			tag_id: '4',
			category_id: '5'
		});
		const giro = row('expense:c4:a1');
		expect(giro).toMatchObject({ label: 'Giro', depth: 1, hasChildren: false, accountId: 1 });
		expect(giro.line.total!.amount).toBe(-50000);
		expect(query(giro.href).getAll('account_id')).toEqual(['1']);
		expect(query(giro.href).getAll('category_id')).toEqual(['4']);
		expect(row('expense:total').href).toContain('category_id=');
	});

	it('shows an opposite-sign link in the table, though it is not drawn', () => {
		expect(row('expense:c6:a1').line.total!.amount).toBe(500);
		expect(row('other:unclassified-out:a3').line.total!.amount).toBe(300);
	});

	it('lists the lines beside the tree as By category does, each with its total and its accounts', () => {
		expect(section('other').rows.map((r) => r.key)).toEqual([
			'other:unclassified-out',
			'other:unclassified-out:a1',
			'other:unclassified-out:a3',
			'other:unclassified-in',
			'other:unclassified-in:a1',
			'other:reconciliations',
			'other:reconciliations:a3',
			'other:reconciliations:a1'
		]);
		expect(
			section('other')
				.rows.filter((r) => r.depth === 0)
				.map((r) => r.label)
		).toEqual(['Unclassified, out', 'Unclassified, in', 'Reconciliations']);
		// the total is the answer's own figure
		const out = row('other:unclassified-out');
		expect(out.line.total!.amount).toBe(-2200);
		expect(out.line.count).toBe(3);
		// linked as By category links the line: the page's scope, no account filter
		expect(Object.fromEntries(query(out.href))).toEqual({
			from: '2026-10-01',
			to: '2026-10-31',
			tag_id: '4',
			uncategorised: 'true',
			direction: 'out'
		});
		expect(row('other:reconciliations').line.total!.amount).toBe(3900);
		expect(Object.fromEntries(query(row('other:reconciliations').href))).toEqual({
			from: '2026-10-01',
			to: '2026-10-31',
			tag_id: '4',
			type: 'reconciliation'
		});
		const account = row('other:unclassified-in:a1');
		expect(query(account.href).getAll('account_id')).toEqual(['1']);
		expect(query(account.href).getAll('direction')).toEqual(['in']);
	});

	it('leaves out a line with no entries', () => {
		const zero = { total: line(0), accounts: [] };
		const rows = accountTable(
			byAccount({ unclassified_in: zero, reconciliations: zero }),
			lookups.categories,
			lookups.accounts,
			scope
		).find((s) => s.key === 'other')!.rows;
		expect(rows.filter((r) => r.depth === 0).map((r) => r.key)).toEqual(['other:unclassified-out']);
	});

	it('gives a sending account its total, as a plain figure: no filter lists exactly its legs', () => {
		const group = row('transfers:a1');
		expect(group).toMatchObject({ label: 'Giro', depth: 0, hasChildren: true, href: null });
		// the answer's total (not the sum of the links beneath it), with its count
		expect(group.line.total!.amount).toBe(-110000);
		expect(group.line.count).toBe(3);
		expect(group.title).toMatch(/no second account/);
	});

	it('lists each sending account with the receiving accounts beneath it', () => {
		expect(section('transfers').rows.map((r) => r.key)).toEqual([
			'transfers:a1',
			'transfers:a1:a2',
			'transfers:a1:a3',
			'transfers:a2',
			'transfers:a2:a1',
			'transfers:a3',
			'transfers:a3:a2'
		]);
		const leg = row('transfers:a1:a2');
		expect(leg.line.total!.amount).toBe(-100000);
		expect(Object.fromEntries(query(leg.href))).toMatchObject({
			account_id: '1',
			counter_account_id: '2',
			type: 'transfer',
			direction: 'out'
		});
		// one that could not be valued stays in the table
		expect(row('transfers:a1:a3').line.total).toBeNull();
	});
});
