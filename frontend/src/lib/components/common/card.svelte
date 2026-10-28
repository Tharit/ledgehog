<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';
	import { cn } from '#lib/utils.js';

	// The one card (design §5 Surfaces): `card` surface, 1px border, 12px radius, the card shadow.
	// `padded` (20px) is a self-contained block: a figure, a form, a chart, a short list; its title
	// sits inside. `flush` is a page's list or table: no padding, rows edge to edge divided by
	// hairlines. A flush card does not clip (overflow-hidden would break a table's sticky header
	// row): its first and last child instead round their own outer corners, so a tinted header
	// row or a hovered last row follows the card's curve. A table goes in a flush card as the
	// first and last child, a list as `element="ul"` with `li` rows.
	type Props = Omit<HTMLAttributes<HTMLElement>, 'children' | 'class'> & {
		variant?: 'padded' | 'flush';
		element?: string;
		class?: string;
		children?: Snippet;
	};

	let {
		variant = 'padded',
		element = 'div',
		class: className,
		children,
		...rest
	}: Props = $props();
</script>

<svelte:element
	this={element}
	class={cn(
		'rounded-xl border border-border bg-card shadow-card',
		variant === 'padded'
			? 'p-5'
			: '[&>:first-child]:rounded-t-[11px] [&>:last-child]:rounded-b-[11px]',
		className
	)}
	{...rest}
>
	{@render children?.()}
</svelte:element>
