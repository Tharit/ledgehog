<script lang="ts">
	import { dimensionVars } from '#lib/theme/dimensions.js';
	import { iconFor } from '#lib/theme/icons.js';
	import { cn } from '#lib/utils.js';

	// An icon drawn in its dimension colour on its tint, in a rounded square: 24px in compact
	// rows, 32px in comfortable ones (design §3). `initial` stands in for the icon (a payee
	// without one). Decorative unless a `label` is given.
	let {
		icon = null,
		color = null,
		initial,
		size = 'compact',
		label,
		class: className
	}: {
		icon?: string | null;
		color?: string | null;
		initial?: string;
		size?: 'compact' | 'comfortable';
		label?: string;
		class?: string;
	} = $props();

	const vars = $derived(dimensionVars(color));
	const Icon = $derived(iconFor(icon));
</script>

<span
	class={cn(
		'inline-flex shrink-0 items-center justify-center rounded-sm bg-(--tile-bg) text-(--tile-fg)',
		size === 'compact' ? 'size-6' : 'size-8',
		className
	)}
	style:--tile-bg={vars.tint}
	style:--tile-fg={vars.fg}
	role={label ? 'img' : undefined}
	aria-label={label}
	aria-hidden={label ? undefined : 'true'}
>
	{#if initial}
		<span class="text-xs leading-none font-semibold">{initial}</span>
	{:else}
		<Icon size={size === 'compact' ? 16 : 18} strokeWidth={1.75} />
	{/if}
</span>
