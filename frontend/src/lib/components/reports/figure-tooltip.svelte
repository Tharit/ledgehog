<script lang="ts" module>
	/** A row of a tooltip: its lead tile is the `icon` name on the `color` name (design §6); a row
	 *  with no subject has no `icon` and no tile. */
	export type TipRow = { label: string; value: string; icon?: string; color?: string };
	export type Tip = { title?: string; rows: TipRow[] };
</script>

<script lang="ts">
	import { getChartContext, Tooltip } from 'layerchart';
	import FigureTip from './figure-tip.svelte';

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
		<FigureTip {tip} />
	{/if}
</Tooltip.Root>
