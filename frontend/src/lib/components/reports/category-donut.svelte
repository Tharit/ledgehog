<script lang="ts">
	import { PieChart } from 'layerchart';
	import * as Chart from '#lib/components/ui/chart/index.js';
	import { formatMoney } from '#lib/format/index.js';
	import type { Slice } from '#lib/reports/charts.js';
	import { dimensionVars } from '#lib/theme/dimensions.js';
	import FigureTooltip from './figure-tooltip.svelte';

	// The whole of a kind in one range as a donut (design §8: only where the whole matters more than
	// the ranking): the largest categories in their resolved colours, "Other" in stone. The table
	// beside it is the data; a slice's tooltip names its signed amount.
	let {
		slices,
		currency,
		locale = 'en',
		sign = -1
	}: {
		slices: readonly Slice[];
		currency: string;
		locale?: string;
		/** the sign of the kind's amounts: -1 for expense, 1 for income */
		sign?: 1 | -1;
	} = $props();

	const data = $derived(
		slices.map((s) => ({
			key: s.key,
			label: s.label,
			value: s.value,
			color: dimensionVars(s.color).fg,
			icon: s.icon,
			tile: s.color
		}))
	);
	const config = $derived(
		Object.fromEntries(
			slices.map((s) => [s.key, { label: s.label, color: dimensionVars(s.color).fg }])
		)
	);
	const money = (minor: number) => formatMoney(sign * minor, currency, { locale });
</script>

<!-- An explicit width: in a grid cell the auto margins make the box shrink to its content, and the
	chart (width: 100%) is that content, so the square collapsed to nothing. -->
<Chart.Container {config} class="mx-auto aspect-square w-full max-w-64" data-slot="category-donut">
	<PieChart
		{data}
		key="key"
		label="label"
		value="value"
		c="color"
		innerRadius={-28}
		padAngle={0.01}
	>
		{#snippet tooltip()}
			<FigureTooltip
				describe={(d) => ({
					rows: [{ label: d.label, value: money(d.value), icon: d.icon, color: d.tile }]
				})}
			/>
		{/snippet}
	</PieChart>
</Chart.Container>
