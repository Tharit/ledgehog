<script lang="ts">
	import { BarChart } from 'layerchart';
	import * as Chart from '#lib/components/ui/chart/index.js';
	import { formatCompactAmount, formatMoney } from '#lib/format/index.js';
	import type { StackRow, StackSeries } from '#lib/reports/charts.js';
	import { dimensionVars } from '#lib/theme/dimensions.js';
	import FigureTooltip from './figure-tooltip.svelte';

	// The top categories and "Other" as stacked bars per period, in the categories' resolved colours
	// ("Other" in stone). The bars are magnitudes; the axis and the tooltip write the kind's sign.
	let {
		series,
		rows,
		currency,
		sign = -1,
		locale = 'en'
	}: {
		series: readonly StackSeries[];
		rows: readonly StackRow[];
		currency: string;
		/** the sign of the kind's amounts: -1 for expense, 1 for income */
		sign?: 1 | -1;
		locale?: string;
	} = $props();

	const chartSeries = $derived(
		series.map((s) => ({ key: s.key, label: s.label, color: dimensionVars(s.color).fg }))
	);
	const config = $derived(
		Object.fromEntries(chartSeries.map((s) => [s.key, { label: s.label, color: s.color }]))
	);
	const money = (minor: number) => formatMoney(sign * minor, currency, { locale });
</script>

<div class="flex flex-col gap-2" data-slot="category-stack-chart">
	<Chart.Container {config} class="aspect-[2/1] w-full">
		<BarChart
			data={[...rows]}
			x="label"
			series={chartSeries}
			seriesLayout="stack"
			bandPadding={0.3}
			grid={{ x: false }}
			props={{
				yAxis: { format: (v: number) => formatCompactAmount(sign * v, currency, locale) }
			}}
		>
			{#snippet tooltip()}
				<FigureTooltip
					describe={(d: StackRow) => ({
						title: String(d.label),
						rows: chartSeries
							.filter((s) => Number(d[s.key]) !== 0)
							.map((s) => ({ label: s.label, value: money(Number(d[s.key])), color: s.color }))
					})}
				/>
			{/snippet}
		</BarChart>
	</Chart.Container>
	<ul class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" data-slot="chart-legend">
		{#each chartSeries as s (s.key)}
			<li class="flex items-center gap-1.5">
				<span class="size-2.5 rounded-[2px]" style:background-color={s.color} aria-hidden="true"
				></span>
				{s.label}
			</li>
		{/each}
	</ul>
</div>
