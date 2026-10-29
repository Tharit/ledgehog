<script lang="ts">
	// A count as a chip (design §5): a cut-out of the sidebar, its numerals in the sidebar's own
	// colour on a muted fill, tabular so a changing count does not jiggle.
	let { count }: { count: number | string } = $props();
</script>

<span
	class="inline-flex h-5 shrink-0 items-center rounded-sm bg-muted-foreground px-1.5 text-xs font-medium text-sidebar tabular-nums"
	data-slot="count-chip"
>
	{count}
</span>
