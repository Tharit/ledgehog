// What a category merge or delete preview says, in words (patterns §6): rendered from the dry-run
// answer, never computed here (architecture §6.3).
import { describeHeld } from '#lib/dimensions/errors.js';
import { plural } from '#lib/dimensions/text.js';
import type { Category, CategoryDeleteOut, CategoryMergeOut } from '#lib/types/domain.js';

export type MergeSummary = {
	/** "Merges 2 categories" */
	headline: string;
	/** "Fruit into Food › Fruit (4 entries, 1 rule)", deepest first, the requested merge last */
	pairs: string[];
	/** "Apples moves under Food" */
	moved: string[];
	/** "Repoints 12 entries and 3 rules" */
	totals: string;
	/** what does not happen, and what the target keeps */
	notes: string[];
};

export function categoryMergeSummary(
	out: CategoryMergeOut,
	categories: ReadonlyMap<number, Category>
): MergeSummary {
	const nameOf = (id: number, fallback = 'another category') =>
		categories.get(id)?.name ?? fallback;
	const target = nameOf(out.target_id, 'the target');
	return {
		headline: `Merges ${plural(out.pairs.length, 'category', 'categories')}`,
		pairs: out.pairs.map(
			(p) =>
				`${p.source_name} into ${p.target_name} (${plural(p.entries, 'entry', 'entries')}, ${plural(p.rules, 'rule', 'rules')})`
		),
		moved: out.moved_children.map((m) => `${m.name} moves under ${nameOf(m.to_id)}`),
		totals: `Repoints ${plural(out.entry_count, 'entry', 'entries')} and ${plural(out.rule_ids.length, 'rule', 'rules')}`,
		notes: ['Nothing returns to review.', `${target} keeps its own icon and colour.`]
	};
}

export type DeleteSummary = {
	deletable: boolean;
	/** why it cannot be deleted; empty when it can */
	reason: string;
};

export function categoryDeleteSummary(out: CategoryDeleteOut): DeleteSummary {
	if (out.deletable) return { deletable: true, reason: '' };
	const held = describeHeld(out.held);
	return {
		deletable: false,
		reason: `${out.category.name} cannot be deleted: it holds ${held}. Merge it into another category instead.`
	};
}
