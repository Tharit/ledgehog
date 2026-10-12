// Where a category's icon and colour come from (design.md §3): its own, its nearest ancestor's, or
// the default. Resolution itself is `resolveCategory`; this only explains it, as a hint.
import { isKnownIcon } from '#lib/theme/icons.js';
import { isKnownColor } from '#lib/theme/resolve.js';
import type { Category } from '#lib/types/domain.js';

export type LookSource = { own: true } | { own: false; from: Category | null };

function sourceOf(
	category: Category,
	categories: ReadonlyMap<number, Category>,
	has: (c: Category) => boolean
): LookSource {
	if (has(category)) return { own: true };
	const seen = new Set<number>([category.id]);
	let current = category.parent_id === null ? undefined : categories.get(category.parent_id);
	while (current && !seen.has(current.id)) {
		if (has(current)) return { own: false, from: current };
		seen.add(current.id);
		current = current.parent_id === null ? undefined : categories.get(current.parent_id);
	}
	return { own: false, from: null };
}

export function lookSources(
	category: Category,
	categories: ReadonlyMap<number, Category>
): { icon: LookSource; color: LookSource } {
	return {
		icon: sourceOf(category, categories, (c) => isKnownIcon(c.icon)),
		color: sourceOf(category, categories, (c) => isKnownColor(c.color))
	};
}

/**
 * "inherited from Food", "icon inherited from Food, colour default"…: what the row says about the
 * parts of its look it does not carry itself. Null when it has both of its own.
 */
export function inheritHint(
	category: Category,
	categories: ReadonlyMap<number, Category>
): string | null {
	const { icon, color } = lookSources(category, categories);
	if (icon.own && color.own) return null;
	const describe = (source: LookSource) =>
		source.own ? null : source.from ? `inherited from ${source.from.name}` : 'default';
	const [i, c] = [describe(icon), describe(color)];
	if (i === c) return i === 'default' ? 'default icon and colour' : `icon and colour ${i}`;
	if (i === null) return `colour ${c}`;
	if (c === null) return `icon ${i}`;
	return `icon ${i}, colour ${c}`;
}
