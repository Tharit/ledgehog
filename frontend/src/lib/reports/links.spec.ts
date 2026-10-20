import { describe, expect, it } from 'vitest';
import { buildLookups } from '#lib/ledger/lookups.js';
import { category } from '#lib/ledger/fixtures.js';
import {
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
});
