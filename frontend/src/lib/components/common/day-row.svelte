<script lang="ts">
	import { cn } from '#lib/utils.js';

	// A day row (design §5): the date of the rows beneath it, within a subgroup row. A lighter tint
	// of `muted` (mixed with the card, so it is opaque where it sticks), its label in the labels'
	// size and weight (§4) in `muted-foreground`. A full-width row of the surrounding grid. With
	// `top` it sticks beneath the subgroup row (the header row's height plus the subgroup row's)
	// while its rows are in view: it must be the first child of an element holding just that day.
	let {
		label,
		top,
		class: className,
		...rest
	}: {
		label: string;
		/** a CSS length: stick this far from the top of the page */
		top?: string;
		class?: string;
		[key: `data-${string}`]: string | number | boolean | undefined;
	} = $props();
</script>

<div
	role="row"
	class={cn(
		'block h-7 border-b border-border bg-[color-mix(in_oklab,var(--color-muted)_60%,var(--color-card))] px-3',
		top !== undefined && 'sticky z-[8]',
		className
	)}
	style:top
	{...rest}
>
	<div
		role="gridcell"
		class="flex h-full items-center text-xs font-medium text-muted-foreground"
		data-slot="day-label"
	>
		{label}
	</div>
</div>
