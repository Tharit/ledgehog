<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { IconComponent } from '#lib/theme/icons.js';
	import { cn } from '#lib/utils.js';

	// A flush card's title row (design §5): the heading glyph (§6), the title and its count, its
	// actions at the right. It is the card's first child and forms one `surface-muted` band with the
	// header row directly beneath (give that row no rounded top and no tint of its own beyond
	// `bg-muted`): the title in the section heading's size with space above it, no hairline between
	// the two. `id` names the heading so the card can be labelled by it.
	type Props = {
		id?: string;
		title: string;
		count?: string;
		icon?: IconComponent | null;
		actions?: Snippet;
		class?: string;
	};

	let { id, title, count, icon: Icon = null, actions, class: className }: Props = $props();
</script>

<div
	class={cn('flex items-center gap-3 bg-muted px-3 pt-2 pb-1.5', className)}
	data-slot="card-title"
>
	<h2 {id} class="flex min-w-0 items-center gap-2 text-base font-semibold">
		{#if Icon}
			<Icon
				size={16}
				strokeWidth={1.75}
				class="shrink-0 text-muted-foreground"
				aria-hidden="true"
			/>
		{/if}
		<span>{title}</span>
		{#if count !== undefined}
			<span class="font-normal text-muted-foreground" data-slot="title-count">({count})</span>
		{/if}
	</h2>
	{#if actions}
		<div class="ml-auto flex items-center gap-2">{@render actions()}</div>
	{/if}
</div>
