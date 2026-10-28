<script lang="ts">
	import type { Snippet } from 'svelte';
	import ActionButton from './action-button.svelte';
	import Card from './card.svelte';

	// An empty list (patterns §11.6): what is missing, one sentence on the next step and, when the
	// page has one, its add action as a button. A card, left-aligned (design §7).
	let {
		title,
		actionLabel,
		onaction,
		actionHref,
		actionDisabled = false,
		children
	}: {
		/** "No categories yet" */
		title: string;
		/** the page's add action: "Add category" */
		actionLabel?: string;
		onaction?: () => void;
		/** the action leads to a route (a page that adds, "Add rule") */
		actionHref?: string;
		actionDisabled?: boolean;
		/** the next step, one sentence */
		children: Snippet;
	} = $props();
</script>

<Card data-slot="empty" class="flex flex-col items-start gap-3 text-sm">
	<div class="flex flex-col gap-1">
		<h3 class="text-base font-semibold">{title}</h3>
		<p class="max-w-prose text-muted-foreground">{@render children()}</p>
	</div>
	{#if actionLabel && (onaction || actionHref)}
		<ActionButton href={actionHref} disabled={actionDisabled} onclick={onaction}>
			{actionLabel}
		</ActionButton>
	{/if}
</Card>
