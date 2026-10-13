<script lang="ts">
	import ActionButton from './action-button.svelte';

	// Title, one-sentence description and the page's one primary action, at the right of the title
	// row at the same size on every screen (patterns §11.7). The action is the page's "Add"; a page
	// that has none passes none. `level` is 1 on a route of its own, 2 under the Settings tabs.
	let {
		title,
		description,
		level = 2,
		actionLabel,
		onaction,
		actionHref,
		actionDisabled = false
	}: {
		title: string;
		description?: string;
		level?: 1 | 2;
		/** "Add category" */
		actionLabel?: string;
		onaction?: () => void;
		/** the action leads to a route (a page that adds, "Add rule") */
		actionHref?: string;
		actionDisabled?: boolean;
	} = $props();
</script>

<div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2" data-slot="page-header">
	<div class="flex flex-col gap-1">
		<svelte:element
			this={level === 1 ? 'h1' : 'h2'}
			class={level === 1 ? 'text-[28px] font-semibold' : 'text-base font-semibold'}
		>
			{title}
		</svelte:element>
		{#if description}
			<p class="max-w-prose text-sm text-muted-foreground">{description}</p>
		{/if}
	</div>
	{#if actionLabel}
		<ActionButton href={actionHref} disabled={actionDisabled} onclick={onaction} class="shrink-0">
			{actionLabel}
		</ActionButton>
	{/if}
</div>
