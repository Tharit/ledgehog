<script lang="ts">
	import { getChartContext } from 'layerchart';

	// Hands the chart's context to the component that draws the marks: it is only reachable from
	// inside the chart, and the marks show the shared tooltip (figure-tooltip) through it.
	let { onready }: { onready: (chart: ReturnType<typeof getChartContext>) => void } = $props();

	const context = getChartContext();
	$effect(() => onready(context));
</script>
