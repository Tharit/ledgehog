<script lang="ts">
	import { BarChart, Bars, Spline } from 'layerchart';
	import * as Chart from '#lib/components/ui/chart/index.js';
	import { formatCompactAmount, formatMoney } from '#lib/format/index.js';
	import type { IncomeExpensePoint } from '#lib/reports/charts.js';
	import { CHART_SIZE } from './chart-size.js';
	import FigureTooltip from './figure-tooltip.svelte';

	// Income above the zero line, expense below it, the savings as a 2px primary line over them
	// (design §8). The table beside the chart is the data; the tooltip names the three figures.
	let {
		points,
		currency,
		locale = 'en'
	}: {
		points: readonly IncomeExpensePoint[];
		currency: string;
		locale?: string;
	} = $props();

	const config = {
		income: { label: 'Income', color: 'var(--amount-positive)' },
		expense: { label: 'Expense', color: 'var(--amount-negative)' },
		savings: { label: 'Savings', color: 'var(--primary)' }
	} satisfies Chart.ChartConfig;

	const series = [
		{ key: 'income', label: 'Income', color: 'var(--amount-positive)' },
		{ key: 'expense', label: 'Expense', color: 'var(--amount-negative)' }
	];

	// the line can leave the bars' extent: the domain holds all three
	const yDomain = $derived.by((): [number, number] => {
		const all = points.flatMap((p) => [p.income, p.expense, p.savings ?? 0, 0]);
		return [Math.min(...all), Math.max(...all)];
	});

	const money = (minor: number | null) =>
		minor === null ? 'unvalued' : formatMoney(minor, currency, { locale });
</script>

<Chart.Container {config} class={CHART_SIZE} data-slot="income-expense-chart">
	<BarChart
		data={[...points]}
		x="label"
		{series}
		seriesLayout="overlap"
		{yDomain}
		yNice
		bandPadding={0.3}
		grid={{ x: false }}
		props={{
			yAxis: { format: (v: number) => formatCompactAmount(v, currency, locale) }
		}}
	>
		{#snippet marks({ context })}
			{#each context.series.visibleSeries as s (s.key)}
				<Bars seriesKey={s.key} radius={4} rounded="edge" />
			{/each}
			<Spline
				y={(d: IncomeExpensePoint) => d.savings ?? undefined}
				defined={(d: IncomeExpensePoint) => d.savings !== null}
				class="stroke-primary stroke-2"
			/>
		{/snippet}
		{#snippet tooltip()}
			<FigureTooltip
				describe={(d: IncomeExpensePoint) => ({
					title: d.label,
					rows: [
						{ label: 'Income', value: money(d.income), color: 'var(--amount-positive)' },
						{ label: 'Expense', value: money(d.expense), color: 'var(--amount-negative)' },
						{ label: 'Savings', value: money(d.savings), color: 'var(--primary)' }
					]
				})}
			/>
		{/snippet}
	</BarChart>
</Chart.Container>
