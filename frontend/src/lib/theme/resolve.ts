// The client resolves defaults and inheritance for icons and colours (design.md §3, §6): the API
// stores what was given, and a name that is not in the curated sets counts as none.
//   category: no colour/icon of its own -> its parent's, up to the top; then stone / `shapes`
//   account:  no colour -> stone; no icon -> its kind's
//   payee:    no colour -> stone; no icon -> its initial in the icon's place
//   tag:      no colour -> stone

import type { Account, Category, Payee, Tag } from '#lib/types/domain.js';
import {
	DEFAULT_DIMENSION_COLOR,
	DIMENSION_COLORS,
	resolveDimensionColor,
	type DimensionColor
} from './dimensions.js';
import { DEFAULT_ICON, isKnownIcon } from './icons.js';

export type ResolvedLook = { icon: string; color: DimensionColor };

/** The icon an account of a kind has until it is given one. */
export const ACCOUNT_KIND_ICONS: Readonly<Record<string, string>> = {
	checking: 'landmark',
	savings: 'piggy-bank',
	card: 'credit-card',
	cash: 'wallet',
	digital_wallet: 'wallet-cards',
	depot: 'chart-line',
	loan: 'hand-coins',
	asset: 'gem',
	clearance: 'scale'
};

export function isKnownColor(name: string | null | undefined): name is DimensionColor {
	return (DIMENSION_COLORS as readonly string[]).includes(name ?? '');
}

/** A category and its ancestors, the category first; a parent cycle ends the walk. */
function lineage(category: Category, categories: ReadonlyMap<number, Category>): Category[] {
	const chain: Category[] = [];
	const seen = new Set<number>();
	let current: Category | undefined = category;
	while (current && !seen.has(current.id)) {
		seen.add(current.id);
		chain.push(current);
		current = current.parent_id === null ? undefined : categories.get(current.parent_id);
	}
	return chain;
}

export function resolveCategory(
	category: Category | undefined,
	categories: ReadonlyMap<number, Category>
): ResolvedLook {
	const chain = category ? lineage(category, categories) : [];
	const icon = chain.find((c) => isKnownIcon(c.icon))?.icon;
	const color = chain.find((c) => isKnownColor(c.color))?.color;
	return {
		icon: icon ?? DEFAULT_ICON,
		color: isKnownColor(color) ? color : DEFAULT_DIMENSION_COLOR
	};
}

/** "Food › Groceries": the names from the top level down. */
export function categoryPath(
	category: Category,
	categories: ReadonlyMap<number, Category>,
	separator = ' › '
): string {
	return lineage(category, categories)
		.map((c) => c.name)
		.reverse()
		.join(separator);
}

export function resolveAccount(account: Pick<Account, 'icon' | 'color' | 'kind'>): ResolvedLook {
	return {
		icon: isKnownIcon(account.icon)
			? account.icon
			: (ACCOUNT_KIND_ICONS[account.kind] ?? DEFAULT_ICON),
		color: resolveDimensionColor(account.color)
	};
}

/** An account kind's lead tile: the kind's default icon on `stone` (design.md §6). */
export function resolveAccountKind(kind: string): ResolvedLook {
	return { icon: ACCOUNT_KIND_ICONS[kind] ?? DEFAULT_ICON, color: DEFAULT_DIMENSION_COLOR };
}

/** A payee's icon is null when it has none: its initial stands in (design.md §3). */
export function resolvePayee(payee: Pick<Payee, 'icon' | 'color' | 'name'>): {
	icon: string | null;
	color: DimensionColor;
	initial: string;
} {
	const first = Array.from(payee.name.trim())[0];
	return {
		icon: isKnownIcon(payee.icon) ? payee.icon : null,
		color: resolveDimensionColor(payee.color),
		initial: first ? first.toUpperCase() : '?'
	};
}

export function resolveTag(tag: Pick<Tag, 'color'>): { color: DimensionColor } {
	return { color: resolveDimensionColor(tag.color) };
}
