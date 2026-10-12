// The category tree from the flat list (architecture §4.1: `parent_id` links it): the two roots
// (the kinds, not rows), sibling order, descendant sets, move and reorder computation. Pure; the
// server stays the authority on what is allowed (cycles, kinds).
import { categoryPath } from '#lib/theme/resolve.js';
import type { Category } from '#lib/types/domain.js';

export type CategoryKind = 'income' | 'expense';
export const CATEGORY_KINDS: readonly CategoryKind[] = ['expense', 'income'];

export type CategoryNode = { category: Category; children: CategoryNode[] };

/** One visible row of the tree, with what its buttons need to know. */
export type TreeRow = {
	category: Category;
	depth: number;
	hasChildren: boolean;
	collapsed: boolean;
	first: boolean;
	last: boolean;
};

export function compareCategories(a: Category, b: Category): number {
	return a.sort_order - b.sort_order || a.name.localeCompare(b.name) || a.id - b.id;
}

function childrenIndex(categories: readonly Category[]): Map<number | null, Category[]> {
	const ids = new Set(categories.map((c) => c.id));
	const index = new Map<number | null, Category[]>();
	for (const category of categories) {
		// a parent the list does not hold (it should not happen) leaves the category at the top
		const parent =
			category.parent_id !== null && ids.has(category.parent_id) ? category.parent_id : null;
		index.set(parent, [...(index.get(parent) ?? []), category]);
	}
	for (const list of index.values()) list.sort(compareCategories);
	return index;
}

function nodesOf(
	parent: number | null,
	index: Map<number | null, Category[]>,
	seen: Set<number>
): CategoryNode[] {
	return (index.get(parent) ?? [])
		.filter((category) => !seen.has(category.id))
		.map((category) => {
			seen.add(category.id);
			return { category, children: nodesOf(category.id, index, seen) };
		});
}

/** Top-level categories of each kind with their subtrees, siblings by sort order, then name. */
export function buildTree(categories: readonly Category[]): Record<CategoryKind, CategoryNode[]> {
	const index = childrenIndex(categories);
	const seen = new Set<number>();
	const top = nodesOf(null, index, seen);
	return {
		expense: top.filter((n) => n.category.kind !== 'income'),
		income: top.filter((n) => n.category.kind === 'income')
	};
}

/** The rows to draw: depth-first, the children of a collapsed category left out. */
export function visibleRows(
	nodes: readonly CategoryNode[],
	collapsed: ReadonlySet<number>,
	depth = 0
): TreeRow[] {
	return nodes.flatMap((node, i) => {
		const isCollapsed = collapsed.has(node.category.id) && node.children.length > 0;
		return [
			{
				category: node.category,
				depth,
				hasChildren: node.children.length > 0,
				collapsed: isCollapsed,
				first: i === 0,
				last: i === nodes.length - 1
			},
			...(isCollapsed ? [] : visibleRows(node.children, collapsed, depth + 1))
		];
	});
}

/** Every category below this one, at any depth (not the category itself). */
export function descendantIds(id: number, categories: readonly Category[]): Set<number> {
	const index = childrenIndex(categories);
	const found = new Set<number>();
	const walk = (parent: number) => {
		for (const child of index.get(parent) ?? []) {
			if (found.has(child.id)) continue;
			found.add(child.id);
			walk(child.id);
		}
	};
	walk(id);
	return found;
}

/** The categories sharing this one's parent, in display order (the category included). */
export function siblingsOf(category: Category, categories: readonly Category[]): Category[] {
	return categories
		.filter((c) => c.parent_id === category.parent_id && c.kind === category.kind)
		.sort(compareCategories);
}

/** The sort order that puts a new category after the siblings it joins. */
export function nextSortOrder(siblings: readonly Category[]): number {
	return siblings.length === 0 ? 0 : Math.max(...siblings.map((s) => s.sort_order)) + 1;
}

export type SortUpdate = { id: number; sort_order: number };

/**
 * The writes that move a category one place up or down among its siblings. Equal sort orders (all
 * categories start at 0) are common, so the new order is numbered 0, 1, 2…: only the siblings whose
 * number changes are returned. Nothing at the edge.
 */
export function moveWithinSiblings(
	siblings: readonly Category[],
	id: number,
	direction: 'up' | 'down'
): SortUpdate[] {
	const ordered = [...siblings].sort(compareCategories);
	const from = ordered.findIndex((c) => c.id === id);
	const to = direction === 'up' ? from - 1 : from + 1;
	if (from < 0 || to < 0 || to >= ordered.length) return [];
	[ordered[from], ordered[to]] = [ordered[to], ordered[from]];
	return ordered
		.map((c, i) => ({ category: c, sort_order: i }))
		.filter(({ category, sort_order }) => category.sort_order !== sort_order)
		.map(({ category, sort_order }) => ({ id: category.id, sort_order }));
}

export type PickerOption = {
	id: number;
	/** the path "Food › Groceries": searchable and unambiguous */
	label: string;
	depth: number;
	/** why it cannot be chosen; absent when it can */
	disabled?: string;
};

/**
 * The categories a picker offers, in tree order: only those of `kind`, the ones in `exclude` left
 * out and the ones in `disable` shown but not choosable, with the reason.
 */
export function pickerOptions(
	categories: readonly Category[],
	kind: string,
	{
		exclude = new Set<number>(),
		disable = new Map<number, string>()
	}: { exclude?: ReadonlySet<number>; disable?: ReadonlyMap<number, string> } = {}
): PickerOption[] {
	const byId = new Map(categories.map((c) => [c.id, c]));
	const tree = buildTree(categories.filter((c) => c.kind === kind));
	const options: PickerOption[] = [];
	const all = (nodes: readonly CategoryNode[], depth: number) => {
		for (const node of nodes) {
			if (!exclude.has(node.category.id)) {
				options.push({
					id: node.category.id,
					label: categoryPath(node.category, byId),
					depth,
					disabled: disable.get(node.category.id)
				});
			}
			all(node.children, depth + 1);
		}
	};
	all([...tree.expense, ...tree.income], 0);
	return options;
}

/** The list indexed by id. */
export function indexById(categories: readonly Category[]): Map<number, Category> {
	return new Map(categories.map((c) => [c.id, c]));
}

/** The set with `id` added, or removed when it is in. */
export function toggled(ids: ReadonlySet<number>, id: number): Set<number> {
	const next = new Set(ids);
	if (!next.delete(id)) next.add(id);
	return next;
}

/** Where a category cannot be moved to, with the reason: itself, its descendants, where it is. */
export function moveBlocked(
	category: Category,
	categories: readonly Category[]
): Map<number, string> {
	const blocked = new Map<number, string>([[category.id, 'itself']]);
	for (const id of descendantIds(category.id, categories)) blocked.set(id, 'inside it');
	if (category.parent_id !== null) blocked.set(category.parent_id, 'current parent');
	return blocked;
}
