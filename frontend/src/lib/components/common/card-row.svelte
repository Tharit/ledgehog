<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '#lib/utils.js';

	// One quiet row of a card: a muted label and its value at the right. With an `href` the whole
	// row is the link (the ledger or report that lists what the value sums).
	let {
		label,
		href,
		children
	}: {
		label: string;
		href?: string;
		children: Snippet;
	} = $props();
</script>

<svelte:element
	this={href ? 'a' : 'div'}
	{href}
	class={cn(
		'flex items-baseline justify-between gap-3 text-sm',
		href && 'rounded-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring'
	)}
	data-slot="card-row"
>
	<span class="text-muted-foreground">{label}</span>
	<span class="text-right font-medium">{@render children()}</span>
</svelte:element>
