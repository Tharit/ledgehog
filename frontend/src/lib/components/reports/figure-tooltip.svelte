<script lang="ts" module>
	export type TipRow = { label: string; value: string; color?: string };
	export type Tip = { title?: string; rows: TipRow[] };
</script>

<script lang="ts">
	import { getChartContext, Tooltip } from 'layerchart';

	// The tooltip of the report charts, in the look of ui/chart's: the hovered row of data, told in
	// the report's own words (signed amounts, the names of a figure's components). The chart is
	// never the only place a figure is (its table is beside it), so the tooltip is a convenience.
	let {
		describe
	}: {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		describe: (data: any) => Tip | null;
	} = $props();

	const chart = getChartContext();
	const tip = $derived(chart.tooltip.data == null ? null : describe(chart.tooltip.data));
</script>

<Tooltip.Root variant="none">
	{#if tip}
		<div
			class="grid min-w-32 items-start gap-1.5 rounded-lg border border-border/50 bg-background px-2.5 py-1.5 text-xs shadow-xl"
			data-slot="figure-tooltip"
		>
			{#if tip.title}<div class="font-medium">{tip.title}</div>{/if}
			<div class="grid gap-1.5">
				{#each tip.rows as row (row.label)}
					<div class="flex items-center gap-2">
						{#if row.color}
							<span
								class="size-2.5 shrink-0 rounded-[2px]"
								style:background-color={row.color}
								aria-hidden="true"
							></span>
						{/if}
						<span class="flex-1 text-muted-foreground">{row.label}</span>
						<span class="amount font-medium text-foreground">{row.value}</span>
					</div>
				{/each}
			</div>
		</div>
	{/if}
</Tooltip.Root>
