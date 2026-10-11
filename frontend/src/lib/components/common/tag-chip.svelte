<script lang="ts">
	import { dimensionVars } from '#lib/theme/dimensions.js';

	// A flat chip in its dimension colour: the foreground on its tint.
	let { name, color = null }: { name: string; color?: string | null } = $props();

	const vars = $derived(dimensionVars(color));
</script>

<span
	class="inline-flex h-5 max-w-32 shrink-0 items-center rounded-sm bg-(--chip-bg) px-1.5 text-xs font-medium text-(--chip-fg)"
	style:--chip-bg={vars.tint}
	style:--chip-fg={vars.fg}
	title={name}
	data-slot="tag-chip"
>
	<span class="truncate">{name}</span>
</span>
