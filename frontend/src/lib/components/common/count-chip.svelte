<script lang="ts">
	import { dimensionVars } from '#lib/theme/dimensions.js';

	// A count as a chip (design §5): the tag chip's shape in the neutral `stone` of a dimension
	// without a colour, numerals tabular so a changing count does not jiggle.
	let { count }: { count: number | string } = $props();

	const vars = dimensionVars(null);
</script>

<span
	class="inline-flex h-5 shrink-0 items-center rounded-sm bg-(--chip-bg) px-1.5 text-xs font-medium text-(--chip-fg) tabular-nums"
	style:--chip-bg={vars.tint}
	style:--chip-fg={vars.fg}
	data-slot="count-chip"
>
	{count}
</span>
