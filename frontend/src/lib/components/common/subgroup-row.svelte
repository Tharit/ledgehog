<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '#lib/utils.js';

	// A subgroup row (design §5): a cut within one list that keeps its columns, a row among the
	// rows. Untinted; the hairline above is the previous row's own bottom border, and it carries one
	// below like any row. Its label is in the labels' size and weight, `muted-foreground`; `action`
	// (a button or a figure) sits at the right, `children` is a quiet line beneath. It is a full-width
	// row of the surrounding grid, one cell spanning all its columns.
	let {
		label,
		action,
		children,
		class: className,
		...rest
	}: {
		label: string;
		action?: Snippet;
		children?: Snippet;
		class?: string;
		[key: `data-${string}`]: string | number | boolean | undefined;
	} = $props();
</script>

<div role="row" class={cn('block border-b border-border px-3 py-1.5', className)} {...rest}>
	<div role="gridcell" class="flex flex-col gap-1">
		<div class="flex min-h-6 flex-wrap items-center gap-3">
			<span class="text-xs font-medium text-muted-foreground" data-slot="subgroup-label"
				>{label}</span
			>
			{#if action}
				<div class="ml-auto flex items-center gap-2">{@render action()}</div>
			{/if}
		</div>
		{@render children?.()}
	</div>
</div>
