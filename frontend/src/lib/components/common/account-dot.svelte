<script lang="ts">
	import { dimensionVars } from '#lib/theme/dimensions.js';

	// An account in a compact row: an 8px dot in its colour, then its name (design §6).
	let { name, color = null }: { name: string; color?: string | null } = $props();

	const vars = $derived(dimensionVars(color));
</script>

<span class="inline-flex min-w-0 items-center gap-1.5">
	<span
		class="size-2 shrink-0 rounded-full bg-(--dot)"
		style:--dot={vars.fg}
		aria-hidden="true"
		data-slot="account-dot"
	></span>
	<span class="truncate">{name}</span>
</span>
