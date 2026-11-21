<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '#lib/utils.js';

	// A subgroup row (design §5): a cut within one list that keeps its columns (a month, a currency,
	// an account waited for), a band among the rows. Tinted `muted` as the header row, its label in
	// `foreground` in the section heading's size; `action` (a button) sits at the right, `children`
	// is a quiet line beneath. It is a full-width row of the surrounding grid, one cell spanning all
	// its columns. With `top` it sticks beneath the header row (and whatever is above it) while its
	// rows are in view, so it must be the first child of an element holding just those rows: that
	// element ends its sticking. It is `min-h-9` (2.25rem); a sticky one that a day row sticks beneath
	// (the month) has no `children`, so its height is known to that day row.
	let {
		label,
		action,
		children,
		top,
		class: className,
		...rest
	}: {
		label: string;
		action?: Snippet;
		children?: Snippet;
		/** a CSS length: stick this far from the top of the page (the header row's height) */
		top?: string;
		class?: string;
		[key: `data-${string}`]: string | number | boolean | undefined;
	} = $props();
</script>

<div
	role="row"
	class={cn(
		'block min-h-9 border-b border-border bg-muted px-3 py-1',
		top !== undefined && 'sticky z-[9]',
		className
	)}
	style:top
	{...rest}
>
	<div role="gridcell" class="flex flex-col gap-1">
		<div class="flex min-h-6 flex-wrap items-center gap-3">
			<span class="text-base font-semibold text-foreground" data-slot="subgroup-label">{label}</span
			>
			{#if action}
				<div class="ml-auto flex items-center gap-2">{@render action()}</div>
			{/if}
		</div>
		{@render children?.()}
	</div>
</div>
