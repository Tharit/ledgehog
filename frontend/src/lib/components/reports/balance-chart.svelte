<script lang="ts">
	import { LineChart } from 'layerchart';
	import * as Chart from '#lib/components/ui/chart/index.js';
	import { formatCompactAmount, formatMoney, formatPointLabel } from '#lib/format/index.js';
	import type { BalanceLine, BalanceRow } from '#lib/reports/charts.js';
	import { dimensionVars } from '#lib/theme/dimensions.js';
	import { CHART_SIZE } from './chart-size.js';
	import FigureTooltip from './figure-tooltip.svelte';

	// The balance at each month-end: the net worth in the primary colour (2px), each account toggled
	// on in its own colour (design §8). A balance that could not be valued is a gap, never a zero.
	let {
		lines,
		rows,
		currency,
		locale = 'en'
	}: {
		lines: readonly BalanceLine[];
		rows: readonly BalanceRow[];
		currency: string;
		locale?: string;
	} = $props();

	const colorOf = (line: BalanceLine) =>
		line.color === 'primary' ? 'var(--primary)' : dimensionVars(line.color).fg;

	const series = $derived(
		lines.map((line) => ({
			key: line.key,
			label: line.label,
			color: colorOf(line),
			icon: line.icon,
			tile: line.tileColor,
			props: { defined: (d: BalanceRow) => d[line.key] !== null && d[line.key] !== undefined }
		}))
	);
	const config = $derived(
		Object.fromEntries(series.map((s) => [s.key, { label: s.label, color: s.color }]))
	);
	const money = (value: unknown) =>
		typeof value === 'number'
			? formatMoney(value, currency, { locale, showPlus: false })
			: 'unvalued';
</script>

<Chart.Container {config} class={CHART_SIZE} data-slot="balance-chart">
	<LineChart
		data={[...rows]}
		x="date"
		{series}
		props={{
			spline: { class: 'stroke-2' },
			xAxis: {
				format: (d: Date) => formatPointLabel(d.toISOString().slice(0, 10), locale)
			},
			yAxis: { format: (v: number) => formatCompactAmount(v, currency, locale) }
		}}
	>
		{#snippet tooltip()}
			<FigureTooltip
				describe={(d: BalanceRow) => ({
					title: String(d.label),
					rows: series.map((s) => ({
						label: s.label,
						value: money(d[s.key]),
						icon: s.icon,
						color: s.tile
					}))
				})}
			/>
		{/snippet}
	</LineChart>
</Chart.Container>
