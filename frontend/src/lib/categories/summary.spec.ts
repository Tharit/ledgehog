import { describe, expect, it } from 'vitest';
import { category } from '#lib/ledger/fixtures.js';
import type { CategoryDeleteOut, CategoryMergeOut } from '#lib/types/domain.js';
import { categoryDeleteSummary, categoryMergeSummary } from './summary.js';

const categories = new Map(
	[category({ id: 1, name: 'Food' }), category({ id: 2, name: 'Groceries', parent_id: 1 })].map(
		(c) => [c.id, c]
	)
);

const mergeOut: CategoryMergeOut = {
	dry_run: true,
	source_id: 9,
	target_id: 1,
	pairs: [
		{
			source_id: 8,
			source_name: 'Fruit',
			target_id: 3,
			target_name: 'Fruit',
			entries: 4,
			rules: 1
		},
		{
			source_id: 9,
			source_name: 'Eating',
			target_id: 1,
			target_name: 'Food',
			entries: 1,
			rules: 0
		}
	],
	moved_children: [{ id: 7, name: 'Cafes', from_id: 9, to_id: 1 }],
	entry_count: 5,
	entry_ids: [],
	rule_ids: [11],
	settle: null
};

describe('categoryMergeSummary', () => {
	it('counts the merges and lists every pair with its repointed entries and rules', () => {
		const summary = categoryMergeSummary(mergeOut, categories);

		expect(summary.headline).toBe('Merges 2 categories');
		expect(summary.pairs).toEqual([
			'Fruit into Fruit (4 entries, 1 rule)',
			'Eating into Food (1 entry, 0 rules)'
		]);
	});

	it('lists the moved children and the totals', () => {
		const summary = categoryMergeSummary(mergeOut, categories);

		expect(summary.moved).toEqual(['Cafes moves under Food']);
		expect(summary.totals).toBe('Repoints 5 entries and 1 rule');
	});

	it('says nothing returns to review and that the target keeps its look', () => {
		expect(categoryMergeSummary(mergeOut, categories).notes).toEqual([
			'Nothing returns to review.',
			'Food keeps its own icon and colour.'
		]);
	});

	it('speaks in the singular for one merge', () => {
		const one = { ...mergeOut, pairs: [mergeOut.pairs[1]], moved_children: [] };

		expect(categoryMergeSummary(one, categories).headline).toBe('Merges 1 category');
	});
});

const deleteOut = (over: Partial<CategoryDeleteOut>): CategoryDeleteOut => ({
	dry_run: true,
	category: category({ id: 2, name: 'Groceries' }),
	deletable: true,
	held: { entries: 0, rules: 0, children: 0 },
	deleted: false,
	settle: null,
	...over
});

describe('categoryDeleteSummary', () => {
	it('is deletable when nothing holds it', () => {
		expect(categoryDeleteSummary(deleteOut({}))).toEqual({ deletable: true, reason: '' });
	});

	it('names what holds it and points to merge', () => {
		const summary = categoryDeleteSummary(
			deleteOut({ deletable: false, held: { entries: 12, rules: 1, children: 0 } })
		);

		expect(summary.deletable).toBe(false);
		expect(summary.reason).toBe(
			'Groceries cannot be deleted: it holds 12 entries, 1 rule. Merge it into another category instead.'
		);
	});
});
