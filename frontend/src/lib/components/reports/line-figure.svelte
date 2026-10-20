<script lang="ts">
	import AbsentValue from '#lib/components/common/absent-value.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import { unvaluedExplanation, unvaluedNote } from '#lib/reports/figures.js';
	import type { Line } from '#lib/reports/types.js';

	// A Line (spec §8) as the one figure every report is made of (patterns §2): its total in the
	// base currency, signed and with the code; "unvalued" when entries exist and none could be
	// valued; "+ n unvalued" beside a total that omits some. The tooltip names the currencies.
	// Unvalued is never zero. `class` sizes the figure.
	let {
		line,
		locale = 'en',
		showPlus = true,
		showCurrency = true,
		class: className
	}: {
		line: Line;
		locale?: string;
		showPlus?: boolean;
		showCurrency?: boolean;
		class?: string;
	} = $props();

	const explanation = $derived(unvaluedExplanation(line, locale));
</script>

<span class="inline-flex flex-wrap items-baseline gap-x-2" data-slot="line-figure">
	{#if line.total === null}
		<span class={className}><AbsentValue label="unvalued" {explanation} /></span>
	{:else}
		<MoneyDisplay
			minor={line.total.amount}
			currency={line.total.currency}
			{locale}
			{showPlus}
			{showCurrency}
			class={className}
		/>
		{#if line.unvalued.length > 0}
			<span class="text-xs"><AbsentValue label={unvaluedNote(line)} {explanation} /></span>
		{/if}
	{/if}
</span>
