// The dimension colour set (design.md §3): a user picks a name, never a free colour.
// The values live in layout.css as --dim-<name> and --dim-<name>-tint.

export const DIMENSION_COLORS = [
	'forest',
	'sage',
	'olive',
	'teal',
	'slate',
	'lavender',
	'plum',
	'ochre',
	'brown',
	'stone'
] as const;

export type DimensionColor = (typeof DIMENSION_COLORS)[number];

export const DEFAULT_DIMENSION_COLOR: DimensionColor = 'stone';

/** A name that is not in the set counts as none; the default is `stone`. */
export function resolveDimensionColor(name: string | null | undefined): DimensionColor {
	return (DIMENSION_COLORS as readonly string[]).includes(name ?? '')
		? (name as DimensionColor)
		: DEFAULT_DIMENSION_COLOR;
}

/** The CSS custom properties of a colour name: the foreground and its tint. */
export function dimensionVars(name: string | null | undefined): { fg: string; tint: string } {
	const color = resolveDimensionColor(name);
	return { fg: `var(--dim-${color})`, tint: `var(--dim-${color}-tint)` };
}
