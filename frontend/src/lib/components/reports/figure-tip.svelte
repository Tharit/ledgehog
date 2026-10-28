<script lang="ts">
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import type { Tip } from './figure-tooltip.svelte';

	// The body of a report chart's tooltip. A row's lead tile (design §6) is the member or measure
	// it tells, drawn by name: a category in its own colour, a measure in stone.
	let { tip }: { tip: Tip } = $props();
</script>

<div
	class="grid min-w-32 items-start gap-1.5 rounded-lg border border-border/50 bg-background px-2.5 py-1.5 text-xs shadow-xl"
	data-slot="figure-tooltip"
>
	{#if tip.title}<div class="font-medium">{tip.title}</div>{/if}
	<div class="grid gap-1.5">
		{#each tip.rows as row (row.label)}
			<div class="flex items-center gap-2">
				{#if row.icon}
					<DimensionIcon icon={row.icon} color={row.color} size="compact" />
				{/if}
				<span class="flex-1 text-muted-foreground">{row.label}</span>
				<span class="amount font-medium text-foreground">{row.value}</span>
			</div>
		{/each}
	</div>
</div>
