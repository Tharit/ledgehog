<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '#lib/utils.js';

	// A band row (design §5): a cut within one list that keeps its columns, drawn lighter than a
	// subgroup row: the inner cut of a list cut twice (a day), or the only cut of a list cut once (a
	// currency, an account waited for). A lighter tint of `muted` (mixed with the card, so it is
	// opaque where it sticks), its label in the labels' size and weight (§4) in `muted-foreground`;
	// `action` (a compact button, §5 "Controls") sits at the right, `children` is a quiet line
	// beneath. A full-width row of the surrounding grid, one cell spanning all its columns. With
	// `top` it sticks beneath whatever is above it (the header row, or a subgroup row) while its
	// rows are in view: it must be the first child of an element holding just those rows. It is
	// `min-h-7` (1.75rem), which it keeps unless it has `children`.
	let {
		label,
		count,
		action,
		leading,
		children,
		top,
		class: className,
		...rest
	}: {
		label: string;
		/** how many it holds, quiet beside the label, as a section title's count */
		count?: string;
		action?: Snippet;
		/** a control before the label (a checkbox that ticks the band's rows) */
		leading?: Snippet;
		children?: Snippet;
		/** a CSS length: stick this far from the top of the page */
		top?: string;
		class?: string;
		[key: `data-${string}`]: string | number | boolean | undefined;
	} = $props();
</script>

<div
	role="row"
	class={cn(
		'block min-h-7 border-b border-border bg-[color-mix(in_oklab,var(--color-muted)_60%,var(--color-card))] px-3',
		top !== undefined && 'sticky z-[8]',
		className
	)}
	style:top
	{...rest}
>
	<div role="gridcell" class="flex flex-col gap-1 py-0.5">
		<div class="flex min-h-6 flex-wrap items-center gap-3">
			{@render leading?.()}
			<span class="text-xs font-medium text-muted-foreground" data-slot="band-label"
				>{label}{#if count !== undefined}<span class="font-normal" data-slot="band-count"
						>{` (${count})`}</span
					>{/if}</span
			>
			{#if action}
				<div class="ml-auto flex items-center gap-2">{@render action()}</div>
			{/if}
		</div>
		{@render children?.()}
	</div>
</div>
