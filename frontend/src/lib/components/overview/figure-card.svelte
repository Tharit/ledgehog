<script lang="ts">
	import type { Snippet } from 'svelte';

	// One of the Overview's figure cards (overview.md, design §6 comfortable): a title, a large
	// figure (28px / 700) and quiet rows beneath that appear only when they have something to say.
	// While `loading` the figure is a skeleton and the rows are not drawn: a first load only, a
	// refetch keeps the figures on screen (patterns §7).
	let {
		title,
		caption,
		loading = false,
		figure,
		rows
	}: {
		title: string;
		/** what the figure covers ("Oct 2025 – Sep 2026") */
		caption?: string;
		loading?: boolean;
		figure: Snippet;
		rows?: Snippet;
	} = $props();
</script>

<section
	class="flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-card p-5 shadow-card"
	data-slot="figure-card"
	aria-label={title}
	aria-busy={loading || undefined}
>
	<header class="flex flex-col gap-0.5">
		<h2 class="text-sm font-semibold">{title}</h2>
		{#if caption}
			<p class="text-xs text-muted-foreground">{caption}</p>
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
</section>
