import { describe, expect, it } from 'vitest';
import { buildLookups } from '#lib/ledger/lookups.js';
import { category } from '#lib/ledger/fixtures.js';
import {
	accountKindHref,
	categoryHref,
	kindCategoryIds,
	kindHref,
	reconciliationsHref,
	unclassifiedHref,
	unconfirmedHref,
	type Scope
} from './links.js';

const scope: Scope = { from: '2026-10-01', to: '2026-10-31', accountIds: [2], tagIds: [7] };
const { categories } = buildLookups({
	categories: [
		category({ id: 1, name: 'Food', kind: 'expense', parent_id: null }),
		category({ id: 2, name: 'Groceries', kind: 'expense', parent_id: 1 }),
		category({ id: 3, name: 'Home', kind: 'expense', parent_id: null }),
		category({ id: 4, name: 'Salary', kind: 'income', parent_id: null })
	]
});

describe('report links to the ledger', () => {
	it('a category with its descendants, the period and the page filters', () => {
		expect(categoryHref(scope, 1)).toBe(
			'/ledger?from=2026-10-01&to=2026-10-31&account_id=2&category_id=1&tag_id=7'
		);
	});

	it('an "(itself)" row is exact', () => {
		expect(categoryHref(scope, 1, true)).toBe(
			'/ledger?from=2026-10-01&to=2026-10-31&account_id=2&category_id=1&category_descendants=false&tag_id=7'
		);
	});

	it('a whole kind lists its top-level categories as alternatives', () => {
		expect(kindCategoryIds(categories, 'expense')).toEqual([1, 3]);
		expect(kindCategoryIds(categories, 'income')).toEqual([4]);
		expect(kindHref({ ...scope, accountIds: [], tagIds: [] }, 'expense', categories)).toBe(
			'/ledger?from=2026-10-01&to=2026-10-31&category_id=1&category_id=3'
		);
	});

	it('unclassified, reconciliations and unconfirmed use the ledger filters for them', () => {
		const bare: Scope = { ...scope, accountIds: [], tagIds: [] };
		expect(unclassifiedHref(bare, 'out')).toBe(
			'/ledger?from=2026-10-01&to=2026-10-31&uncategorised=true&direction=out'
		);
		expect(unclassifiedHref(bare)).toBe('/ledger?from=2026-10-01&to=2026-10-31&uncategorised=true');
		expect(reconciliationsHref(bare)).toBe(
			'/ledger?from=2026-10-01&to=2026-10-31&type=reconciliation'
		);
		expect(unconfirmedHref(bare)).toBe('/ledger?from=2026-10-01&to=2026-10-31&flag=unconfirmed');
	});

	it('a kind on accounts: the top-level categories of income and expense', () => {
		expect(accountKindHref(scope, 'income', categories, [5])).toBe(
			'/ledger?from=2026-10-01&to=2026-10-31&account_id=5&category_id=4&tag_id=7'
		);
		// the page's own account filter unless the row names others
		const query = new URLSearchParams(accountKindHref(scope, 'expense', categories).split('?')[1]);
		expect(query.getAll('account_id')).toEqual(['2']);
		expect(query.getAll('category_id')).toEqual(['1', '3']);
	});

	it('the transfer kinds are the legs of a direction, paired or not', () => {
		const query = (href: string) => new URLSearchParams(href.split('?')[1]);
		const into = query(accountKindHref(scope, 'transfer_in', categories, [5, 6]));
		expect(into.getAll('account_id')).toEqual(['5', '6']);
		expect(into.getAll('type')).toEqual(['transfer']);
		expect(into.get('direction')).toBe('in');
		expect(into.getAll('tag_id')).toEqual(['7']);
		expect(into.has('category_id')).toBe(false);
		const out = query(accountKindHref(scope, 'transfer_out', categories, [5]));
		expect(out.get('direction')).toBe('out');
		expect(out.has('paired')).toBe(false);
	});
});
