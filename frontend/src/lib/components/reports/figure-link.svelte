<script lang="ts">
	import LineFigure from './line-figure.svelte';
	import type { Line } from '#lib/reports/types.js';

	// A figure of a report that links to the ledger with the equivalent filter (spec §8): the entries
	// behind it are exactly the entries the link lists. Without an `href` it is only the figure (a
	// derived one: its `title` names its components).
	let {
		line,
		href,
		title,
		locale = 'en',
		showCurrency = false,
		label
	}: {
		line: Line;
		href?: string;
		title?: string;
		locale?: string;
		showCurrency?: boolean;
		/** what the link says to a screen reader: "Food, October" */
		label?: string;
	} = $props();
</script>

{#if href}
	<a
		{href}
		{title}
		aria-label={label}
		class="rounded-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
		data-slot="figure-link"
	>
		<LineFigure {line} {locale} {showCurrency} />
	</a>
{:else}
	<span {title} data-slot="figure"><LineFigure {line} {locale} {showCurrency} /></span>
{/if}
