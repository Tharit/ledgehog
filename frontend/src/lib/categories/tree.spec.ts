import { describe, expect, it } from 'vitest';
import { category } from '#lib/ledger/fixtures.js';
import {
	buildTree,
	descendantIds,
	moveWithinSiblings,
	nextSortOrder,
	pickerOptions,
	siblingsOf,
	visibleRows
} from './tree.js';

const food = category({ id: 1, name: 'Food', sort_order: 1 });
const groceries = category({ id: 2, name: 'Groceries', parent_id: 1, sort_order: 0 });
const fruit = category({ id: 3, name: 'Fruit', parent_id: 2, sort_order: 0 });
const travel = category({ id: 4, name: 'Travel', sort_order: 0 });
const salary = category({ id: 5, name: 'Salary', kind: 'income', sort_order: 0 });
const all = [food, groceries, fruit, travel, salary];

describe('buildTree', () => {
	it('splits the top level by kind and orders siblings by sort order, then name', () => {
		const tree = buildTree(all);

		expect(tree.expense.map((n) => n.category.name)).toEqual(['Travel', 'Food']);
		expect(tree.income.map((n) => n.category.name)).toEqual(['Salary']);
		expect(tree.expense[1].children[0].category.name).toBe('Groceries');
		expect(tree.expense[1].children[0].children[0].category.name).toBe('Fruit');
	});

	it('breaks ties by name', () => {
		const tree = buildTree([
			category({ id: 1, name: 'b', sort_order: 0 }),
			category({ id: 2, name: 'a', sort_order: 0 })
		]);

		expect(tree.expense.map((n) => n.category.name)).toEqual(['a', 'b']);
	});

	it('keeps a category whose parent is missing at the top, and survives a cycle', () => {
		const orphan = category({ id: 7, name: 'Orphan', parent_id: 99 });
		const a = category({ id: 8, name: 'A', parent_id: 9 });
		const b = category({ id: 9, name: 'B', parent_id: 8 });

		const tree = buildTree([orphan, a, b]);

		expect(tree.expense.map((n) => n.category.name)).toEqual(['Orphan']);
	});

	it('is empty for no categories', () => {
		expect(buildTree([])).toEqual({ expense: [], income: [] });
	});
});

describe('visibleRows', () => {
	const nodes = buildTree(all).expense;

	it('lists depth first with depth and edge flags', () => {
		const rows = visibleRows(nodes, new Set());

		expect(rows.map((r) => [r.category.name, r.depth])).toEqual([
			['Travel', 0],
			['Food', 0],
			['Groceries', 1],
			['Fruit', 2]
		]);
		expect(rows[0]).toMatchObject({ first: true, last: false, hasChildren: false });
		expect(rows[1]).toMatchObject({ first: false, last: true, hasChildren: true });
	});

	it('leaves out what a collapsed category holds', () => {
		const rows = visibleRows(nodes, new Set([1]));

		expect(rows.map((r) => r.category.name)).toEqual(['Travel', 'Food']);
		expect(rows[1].collapsed).toBe(true);
	});

	it('ignores a collapsed mark on a category without children', () => {
		expect(visibleRows(nodes, new Set([4]))[0].collapsed).toBe(false);
	});
});

describe('descendantIds', () => {
	it('holds every level below, not the category', () => {
		expect(descendantIds(1, all)).toEqual(new Set([2, 3]));
		expect(descendantIds(3, all)).toEqual(new Set());
	});
});

describe('moveWithinSiblings', () => {
	const siblings = (orders: number[]) =>
		orders.map((sort_order, i) => category({ id: i + 1, name: `c${i}`, sort_order }));

	it('numbers a run of equal sort orders so the swap is visible', () => {
		const updates = moveWithinSiblings(siblings([0, 0, 0]), 3, 'up');

		// order was c0, c1, c2; c2 moves up: c0, c2, c1
		expect(updates).toEqual([
			{ id: 3, sort_order: 1 },
			{ id: 2, sort_order: 2 }
		]);
	});

	it('swaps only the two when the numbering is already distinct', () => {
		expect(moveWithinSiblings(siblings([0, 1, 2]), 1, 'down')).toEqual([
			{ id: 2, sort_order: 0 },
			{ id: 1, sort_order: 1 }
		]);
	});

	it('does nothing at the edge or for an unknown id', () => {
		expect(moveWithinSiblings(siblings([0, 1]), 1, 'up')).toEqual([]);
		expect(moveWithinSiblings(siblings([0, 1]), 2, 'down')).toEqual([]);
		expect(moveWithinSiblings(siblings([0, 1]), 99, 'down')).toEqual([]);
	});
});

describe('siblingsOf and nextSortOrder', () => {
	it('finds the categories under the same parent, in order', () => {
		expect(siblingsOf(travel, all).map((c) => c.name)).toEqual(['Travel', 'Food']);
		expect(siblingsOf(groceries, all).map((c) => c.name)).toEqual(['Groceries']);
	});

	it('goes after the last one, or starts at 0', () => {
		expect(nextSortOrder([food, travel])).toBe(2);
		expect(nextSortOrder([])).toBe(0);
	});
});

describe('pickerOptions', () => {
	it('offers one kind in tree order with paths', () => {
		const options = pickerOptions(all, 'expense');

		expect(options.map((o) => o.label)).toEqual([
			'Travel',
			'Food',
			'Food › Groceries',
			'Food › Groceries › Fruit'
		]);
		expect(options.map((o) => o.depth)).toEqual([0, 0, 1, 2]);
	});

	it('leaves the excluded out and marks the disabled with their reason', () => {
		const options = pickerOptions(all, 'expense', {
			exclude: new Set([4]),
			disable: new Map([[2, 'inside Food']])
		});

		expect(options.map((o) => o.id)).toEqual([1, 2, 3]);
		expect(options.find((o) => o.id === 2)?.disabled).toBe('inside Food');
		expect(options.find((o) => o.id === 1)?.disabled).toBeUndefined();
	});
});
