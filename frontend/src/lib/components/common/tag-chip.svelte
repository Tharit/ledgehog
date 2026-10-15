<script lang="ts">
	import XIcon from '@lucide/svelte/icons/x';
	import { dimensionVars } from '#lib/theme/dimensions.js';

	// A flat chip in its dimension colour: the foreground on its tint. With `onremove` it carries a
	// small remove X (only the work panel's Tags row passes it): `opacity-0` until the chip is
	// hovered or holds focus and always visible where there is no hover, like the controls of
	// RowActions (patterns §11.3), so it keeps its place in the layout and in the tab order.
	// Backspace or Delete on the X removes the tag too.
	let {
		name,
		color = null,
		onremove
	}: { name: string; color?: string | null; onremove?: () => void } = $props();

	const vars = $derived(dimensionVars(color));

	function onkeydown(event: KeyboardEvent) {
		if (event.key !== 'Backspace' && event.key !== 'Delete') return;
		event.preventDefault();
		onremove?.();
	}
</script>

<span
	class="group inline-flex h-5 max-w-32 shrink-0 items-center rounded-sm bg-(--chip-bg) px-1.5 text-xs font-medium text-(--chip-fg)"
	style:--chip-bg={vars.tint}
	style:--chip-fg={vars.fg}
	title={name}
	data-slot="tag-chip"
>
	<span class="truncate">{name}</span>
	{#if onremove}
		<button
			type="button"
			title={`Remove tag ${name}`}
			aria-label={`Remove tag ${name}`}
			data-slot="tag-remove"
			class="-mr-1 ml-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded-sm opacity-0 outline-none group-focus-within:opacity-100 group-hover:opacity-100 hover:bg-black/10 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50 [@media(hover:none)]:opacity-100"
			onclick={() => onremove()}
			{onkeydown}
		>
			<XIcon size={12} aria-hidden="true" />
		</button>
	{/if}
</span>
