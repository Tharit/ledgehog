<script lang="ts">
	import type { Snippet } from 'svelte';
	import ActionButton from './action-button.svelte';
	import NoticeLine from './notice-line.svelte';

	// The one quiet line of a view that holds a snapshot (ux/patterns.md §7, ux/views/sync.md "New
	// data"): "New data from a sync — Refresh", without a count. It stands in the view's reserved
	// notice line, so nothing moves when it appears; a notice the view already has (the answer to a
	// write, with its own `noticeAction`) comes first, and the line says the news when that has gone.
	let {
		stale,
		onrefresh,
		notice = null,
		noticeAction
	}: {
		stale: boolean;
		onrefresh: () => void;
		notice?: { text: string; error: boolean } | null;
		/** the action of `notice`, not of the news */
		noticeAction?: Snippet;
	} = $props();

	const shown = $derived(
		notice ?? (stale ? { text: 'New data from a sync —', error: false } : null)
	);
</script>

<NoticeLine notice={shown}>
	{#snippet action()}
		{#if notice}
			{@render noticeAction?.()}
		{:else if stale}
			<ActionButton variant="link" class="h-auto p-0" onclick={onrefresh}>Refresh</ActionButton>
		{/if}
	{/snippet}
</NoticeLine>
