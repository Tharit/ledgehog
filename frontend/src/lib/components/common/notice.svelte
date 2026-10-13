<script lang="ts">
	import type { Snippet } from 'svelte';
	import InfoIcon from '@lucide/svelte/icons/info';

	// A quiet one-line notice: muted text and an info icon, never a banner or a dialog (design §7).
	// An optional `action` (a `link` button such as "Try again") follows the text on the same line.
	let {
		role = 'status',
		children,
		action
	}: { role?: 'status' | 'alert'; children: Snippet; action?: Snippet } = $props();
</script>

<p {role} class="flex items-center gap-2 text-sm text-muted-foreground">
	<InfoIcon size={16} strokeWidth={1.75} class="shrink-0" aria-hidden="true" />
	<span>{@render children()}</span>
	{#if action}{@render action()}{/if}
</p>
