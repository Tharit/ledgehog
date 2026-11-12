<script lang="ts">
	import type { Snippet } from 'svelte';
	import Card from '#lib/components/common/card.svelte';

	// A half-width card of the Overview: a section heading, optionally with a quiet caption under it
	// and a link at the right ("By category →"), and a body of rows (design §6 comfortable).
	let {
		title,
		caption,
		linkLabel,
		href,
		children
	}: {
		title: string;
		caption?: string;
		/** the header link's words, without the arrow */
		linkLabel?: string;
		href?: string;
		children: Snippet;
	} = $props();
</script>

<Card
	element="section"
	class="flex min-w-0 flex-col gap-3"
	data-slot="list-card"
	aria-label={title}
>
	<header class="flex items-baseline justify-between gap-3">
		<div class="flex flex-col">
			<h2 class="text-base font-semibold">{title}</h2>
			{#if caption}<p class="text-xs text-muted-foreground">{caption}</p>{/if}
		</div>
		{#if href && linkLabel}
			<a
				{href}
				class="shrink-0 rounded-sm text-sm font-medium text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
			>
				{linkLabel} &rarr;
			</a>
		{/if}
	</header>
	{@render children()}
</Card>
