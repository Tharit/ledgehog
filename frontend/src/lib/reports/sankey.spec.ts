import { describe, expect, it } from 'vitest';
import { resolveCategory } from '#lib/theme/resolve.js';
import { dimensionVars } from '#lib/theme/dimensions.js';
import { line } from './fixtures.js';
import type { Scope } from './links.js';
import { accountSankey, layerPlan, otherCategoryIds, STAYED_OPACITY } from './sankey.js';
import { byAccount, byAccountLookups } from './trend-fixtures.js';

const { categories, accounts } = byAccountLookups();
const scope: Scope = { from: '2026-10-01', to: '2026-10-31', accountIds: [], tagIds: [4] };

/** A ledger href as its parameters, every name with all its values. */
function query(href: string | null): Record<string, string[]> {
	const params = new URLSearchParams(href!.split('?')[1]);
	return Object.fromEntries([...new Set(params.keys())].map((k) => [k, params.getAll(k)]));
}

const model = () => accountSankey(byAccount(), categories, accounts, scope);
const link = (key: string) => model().links.find((l) => l.key === key)!;
const column = (n: number) =>
	model()
		.nodes.filter((node) => node.column === n)
		.map((node) => node.label);

describe('accountSankey: the nodes', () => {
	it('puts the income side, the receiving accounts, the paying accounts and the expense side in four columns', () => {
		expect(column(0)).toEqual(['Salary', 'Other', 'Unclassified', 'Reconciliations']);
		expect(column(1).sort()).toEqual(['Depot', 'Giro', 'Savings']);
		expect(column(2).sort()).toEqual(['Depot', 'Giro', 'Savings']);
		expect(column(3)).toEqual(['Home', 'Food', 'Other', 'Unclassified', 'Reconciliations']);
		expect(model().fullest).toBe(5);
	});

	it('stands an account in both account columns as two distinct nodes', () => {
		const giro = model().nodes.filter((n) => n.label === 'Giro');
		expect(giro.map((n) => n.column)).toEqual([1, 2]);
		expect(new Set(giro.map((n) => n.key)).size).toBe(2);
		expect(giro.every((n) => n.account)).toBe(true);
	});

	it('stands an account in the paying column for what it received and what it paid', () => {
		// Savings receives a transfer and pays "Other"; it kept nothing, so no band
		const savings = model().links.filter((l) => l.source === '2:a2' || l.target === '2:a2');
		expect(savings.map((l) => l.key).sort()).toEqual(['1:a1>2:a2', '2:a2>3:other']);
	});

	it('orders the side columns as the answer gives them and the accounts by what passes through', () => {
		expect(column(1)).toEqual(['Giro', 'Savings', 'Depot']);
		expect(column(2)).toEqual(['Giro', 'Savings', 'Depot']);
	});

	it('keeps each column in the answer’s order, the neutral nodes last, accounts alike in both columns', () => {
		const m = model();
		const order = (c: number) =>
			m.nodes.filter((n) => n.column === c).map((n) => [n.label, n.order]);
		expect(order(3)).toEqual([
			['Home', 0],
			['Food', 1],
			['Other', 2],
			['Unclassified', 3],
			['Reconciliations', 4]
		]);
		expect(order(0).map(([label]) => label)).toEqual([
			'Salary',
			'Other',
			'Unclassified',
			'Reconciliations'
		]);
		const accountsIn = (c: number) =>
			m.nodes.filter((n) => n.column === c && n.account).map((n) => n.label);
		// Savings and Depot pass through in both columns: the same relative order
		expect(accountsIn(1).filter((l) => l !== 'Giro')).toEqual(
			accountsIn(2).filter((l) => l !== 'Giro')
		);
		expect(accountsIn(1)[0]).toBe('Giro');
		expect(accountsIn(2)[0]).toBe('Giro');
	});

	it('draws a category in its resolved colour and "Other" in stone, an account in its own', () => {
		const nodes = model().nodes;
		const salary = nodes.find((n) => n.key === '0:c5')!;
		expect(salary.color).toBe(resolveCategory(categories.get(5), categories).color);
		expect(salary.account).toBe(false);
		expect(nodes.find((n) => n.key === '0:other')).toMatchObject({
			color: 'stone',
			icon: 'circle-ellipsis'
		});
		expect(nodes.find((n) => n.key === '1:a1')).toMatchObject({ color: 'forest' });
		expect(nodes.find((n) => n.key === '3:unclassified')).toMatchObject({
			color: 'stone',
			icon: 'circle-question-mark'
		});
		expect(nodes.find((n) => n.key === '3:reconciliation')!.icon).toBe('scale');
	});
});

describe('accountSankey: the links', () => {
	it('draws each kind between its columns, as magnitudes with the line signed as booked', () => {
		const m = model();
		expect(m.links.map((l) => l.key).sort()).toEqual(
			[
				'0:c5>1:a1',
				'0:other>1:a2',
				'0:unclassified>1:a1',
				'0:reconciliation>1:a3',
				'1:a1>2:a2',
				'1:a2>2:a1',
				'1:a1>2:a1',
				'1:a3>2:a3',
				'2:a1>3:c4',
				'2:a3>3:c4',
				'2:a1>3:c1',
				'2:a2>3:other',
				'2:a1>3:unclassified',
				'2:a1>3:reconciliation'
			].sort()
		);
		expect(link('2:a1>3:c4')).toMatchObject({ value: 50000, kind: 'category', label: 'Home' });
		expect(link('2:a1>3:c4').line!.total!.amount).toBe(-50000);
		expect(link('0:other>1:a2')).toMatchObject({ kind: 'other', label: 'Other', color: 'stone' });
		expect(link('0:reconciliation>1:a3')).toMatchObject({ kind: 'reconciliation', value: 4000 });
		expect(link('2:a1>3:reconciliation').value).toBe(100);
		expect(link('0:unclassified>1:a1').kind).toBe('unclassified');
	});

	it('takes a category link in its category’s colour and a transfer in stone', () => {
		expect(link('0:c5>1:a1').color).toBe(resolveCategory(categories.get(5), categories).color);
		expect(link('1:a1>2:a2')).toMatchObject({
			kind: 'transfer',
			label: 'Transfer',
			color: 'stone',
			from: 'Giro',
			to: 'Savings',
			value: 100000
		});
		expect(dimensionVars(link('1:a1>2:a2').color).fg).toBe(dimensionVars('stone').fg);
	});

	it('draws a transfer there and back as two links', () => {
		expect(link('1:a1>2:a2').value).toBe(100000);
		expect(link('1:a2>2:a1').value).toBe(5000);
	});

	it('draws the income that stayed as a band to the account itself, derived and without a link', () => {
		const band = link('1:a1>2:a1');
		expect(band).toMatchObject({
			kind: 'stayed',
			value: 202000,
			href: null,
			line: null,
			color: 'stone'
		});
		expect(band.stayed).toEqual({ received: 302000, transferredOut: 100000 });
		expect(link('1:a3>2:a3').stayed).toEqual({ received: 4000, transferredOut: 0 });
		expect(STAYED_OPACITY).toBeLessThan(0.35);
	});

	it('does not draw a link of the other sign, and names it in a note', () => {
		const m = model();
		expect(m.links.some((l) => l.key === '2:a1>3:c6')).toBe(false);
		expect(m.links.some((l) => l.key === '2:a3>3:unclassified')).toBe(false);
		expect(m.links.some((l) => l.key === '1:a3>2:a2')).toBe(false);
		expect(m.notes.opposite.map((o) => [o.from, o.to, o.line.total!.amount])).toEqual([
			['Giro', 'Refunds', 500],
			['Depot', 'Unclassified', 300],
			['Depot', 'Savings', 300]
		]);
		expect(query(m.notes.opposite[0].href)).toMatchObject({
			account_id: ['1'],
			category_id: ['6']
		});
	});

	it('does not draw a link whose total could not be valued, and does not note it either', () => {
		const m = model();
		expect(m.links.some((l) => l.key === '1:a1>2:a3')).toBe(false);
		expect(m.notes.opposite.some((o) => o.to === 'Depot' && o.from === 'Giro')).toBe(false);
	});

	it('draws nothing for a side with no drawn link, and no node for it', () => {
		const m = accountSankey(
			byAccount({ unclassified_in: [], income: { ...byAccount().income, other: [] } }),
			categories,
			accounts,
			scope
		);
		expect(m.nodes.some((n) => n.key === '0:unclassified' || n.key === '0:other')).toBe(false);
	});

	it('takes every top-level category as a slice when the answer has no `top`', () => {
		const answer = byAccount();
		const m = accountSankey(
			byAccount({ income: { ...answer.income, slices: null, other: null } }),
			categories,
			accounts,
			scope
		);
		expect(m.links.some((l) => l.key === '0:c7>1:a2')).toBe(true);
		expect(m.nodes.some((n) => n.key === '0:other')).toBe(false);
	});
});

describe('accountSankey: the notes', () => {
	it('names the transfer legs that cannot be drawn, with their count', () => {
		expect(model().notes.undrawn).toEqual(byAccount().undrawn);
	});

	it('has none when there are no such legs', () => {
		const m = accountSankey(byAccount({ undrawn: line(0) }), categories, accounts, scope);
		expect(m.notes.undrawn).toBeNull();
	});
});

describe('accountSankey: every link drills into the ledger with its filter', () => {
	const period = { from: ['2026-10-01'], to: ['2026-10-31'], tag_id: ['4'] };

	it('a category on an account: the account and the category with its descendants', () => {
		expect(query(link('0:c5>1:a1').href)).toEqual({
			...period,
			account_id: ['1'],
			category_id: ['5']
		});
		expect(query(link('2:a3>3:c4').href)).toEqual({
			...period,
			account_id: ['3'],
			category_id: ['4']
		});
	});

	it('"Other" on an account: each category it holds, not those of the other sign', () => {
		expect(query(link('0:other>1:a2').href)).toEqual({
			...period,
			account_id: ['2'],
			category_id: ['7']
		});
		// Refunds (6) is of the other sign: in no slice and not in "Other"
		expect(query(link('2:a2>3:other').href)).toEqual({
			...period,
			account_id: ['2'],
			category_id: ['8']
		});
		expect(otherCategoryIds(byAccount(), 'expense')).toEqual([8]);
		expect(otherCategoryIds(byAccount(), 'income')).toEqual([7]);
	});

	it('unclassified in and out: the account, uncategorised and the direction', () => {
		expect(query(link('0:unclassified>1:a1').href)).toEqual({
			...period,
			account_id: ['1'],
			uncategorised: ['true'],
			direction: ['in']
		});
		expect(query(link('2:a1>3:unclassified').href)).toMatchObject({
			uncategorised: ['true'],
			direction: ['out']
		});
	});

	it('reconciliations: the account and the type', () => {
		expect(query(link('0:reconciliation>1:a3').href)).toEqual({
			...period,
			account_id: ['3'],
			type: ['reconciliation']
		});
		expect(query(link('2:a1>3:reconciliation').href)).toMatchObject({
			account_id: ['1'],
			type: ['reconciliation']
		});
	});

	it('a transfer from A to B: A, B as the counter-account, the type and the direction out', () => {
		expect(query(link('1:a1>2:a2').href)).toEqual({
			...period,
			account_id: ['1'],
			counter_account_id: ['2'],
			type: ['transfer'],
			direction: ['out']
		});
		expect(query(link('1:a2>2:a1').href)).toMatchObject({
			account_id: ['2'],
			counter_account_id: ['1']
		});
	});

	it('carries no account filter of the page: there is none', () => {
		for (const l of model().links.filter((x) => x.href)) {
			expect(query(l.href).account_id).toHaveLength(1);
		}
	});
});

describe('layerPlan', () => {
	const none = {
		unclassified_in: [],
		unclassified_out: [],
		reconciliations: [],
		transfers: [],
		undrawn: line(0),
		stayed: []
	};
	const link = (account_id: number, total: number) => ({ account_id, line: line(total) });

	it('numbers the four columns 0 to 3 when a path runs through them', () => {
		const plan = layerPlan(model());
		expect(plan.layers).toEqual({ 0: 0, 1: 1, 2: 2, 3: 3 });
		expect(plan.spine).toEqual([]);
	});

	it('leaves no gap for a column nobody stands in', () => {
		const answer = byAccount(none);
		const expenseOnly = accountSankey(
			{
				...answer,
				income: { total: line(0), categories: [], slices: [], other: [] }
			},
			categories,
			accounts,
			scope
		);
		const plan = layerPlan(expenseOnly);
		expect(plan.layers).toEqual({ 2: 0, 3: 1 });
		expect(plan.spine).toEqual([]);
	});

	it('connects neighbouring columns with nothing when no path runs through every column', () => {
		// Giro keeps its salary, Savings pays Home: no path from Salary to Home
		const answer = byAccount({
			...none,
			income: {
				total: line(300000),
				categories: [{ category_id: 5, total: line(300000), accounts: [link(1, 300000)] }],
				slices: [5],
				other: []
			},
			expense: {
				total: line(-5000),
				categories: [{ category_id: 4, total: line(-5000), accounts: [link(2, -5000)] }],
				slices: [4],
				other: []
			},
			stayed: [{ account_id: 1, amount: { amount: 300000, currency: 'EUR' } }]
		});
		const plan = layerPlan(accountSankey(answer, categories, accounts, scope));
		expect(plan.layers).toEqual({ 0: 0, 1: 1, 2: 2, 3: 3 });
		expect(plan.spine).toEqual([
			{ source: '0:c5', target: '1:a1' },
			{ source: '1:a1', target: '2:a1' },
			{ source: '2:a1', target: '3:c4' }
		]);
	});
});
