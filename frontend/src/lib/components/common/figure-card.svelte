<script lang="ts">
	import type { Snippet } from 'svelte';
	import Card from '#lib/components/common/card.svelte';
	import type { IconComponent } from '#lib/theme/icons.js';

	// A figure card (overview.md, design §6 comfortable): a header of an optional icon and the title
	// with a one-line subtitle under it, a large figure (28px / 700) and quiet rows beneath that
	// appear only when they have something to say. The Overview's four cards pass an icon and a
	// subtitle and put nothing but rows under the figure, so their rows begin on the same line; while
	// `loading` without a subtitle yet, a bar holds its line so that the header stays two lines
	// tall. While `loading` the figure is a skeleton and the rows are not drawn: a first load only,
	// a refetch keeps the figures on screen (patterns §7).
	let {
		title,
		icon: Icon,
		caption,
		loading = false,
		figure,
		rows
	}: {
		title: string;
		/** a Lucide icon drawn before the title */
		icon?: IconComponent;
		/** what the figure covers ("Oct 2025 – Sep 2026"), one line */
		caption?: string;
		loading?: boolean;
		figure: Snippet;
		rows?: Snippet;
	} = $props();
</script>

<Card
	element="section"
	class="flex min-w-0 flex-col gap-3"
	data-slot="figure-card"
	aria-label={title}
	aria-busy={loading || undefined}
>
	<header class="flex flex-col gap-0.5">
		<h2 class="flex items-center gap-1.5 text-sm font-semibold">
			{#if Icon}<Icon
					size={16}
					strokeWidth={1.75}
					class="text-muted-foreground"
					aria-hidden="true"
				/>{/if}
			{title}
		</h2>
		{#if caption}
			<p class="truncate text-xs text-muted-foreground">{caption}</p>
		{:else if loading}
			<div class="h-4 w-24 animate-pulse rounded bg-muted" data-slot="caption-skeleton"></div>
		{/if}
	</header>
	{#if loading}
		<div class="h-9 w-32 animate-pulse rounded-md bg-muted" data-slot="figure-skeleton"></div>
	{:else}
		<div class="text-[28px] leading-tight font-bold">{@render figure()}</div>
		{#if rows}
			<div class="flex flex-col gap-1.5 text-sm">{@render rows()}</div>
		{/if}
	{/if}
</Card>
