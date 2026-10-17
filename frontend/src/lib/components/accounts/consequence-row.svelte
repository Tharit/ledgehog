<script lang="ts">
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import type { Entry } from '#lib/types/domain.js';

	// One entry of a consequence list (patterns §6) in a dialog: date and amount keep their width, the
	// text between them shrinks and truncates (the full text is its tooltip), so a row never pushes
	// past the dialog. `note` is a short word after the text ("confirmed", "in review").
	let {
		entry,
		locale = 'en',
		note
	}: {
		entry: Pick<Entry, 'booked_on' | 'amount' | 'description' | 'display_text'>;
		locale?: string;
		note?: string;
	} = $props();

	const text = $derived(entry.description ?? entry.display_text ?? '');
</script>

<li
	class="flex min-w-0 items-baseline gap-2 border-b border-border py-0.5 text-[13px]"
	data-slot="consequence-row"
>
	<span class="shrink-0"><DateDisplay date={entry.booked_on} {locale} /></span>
	<span class="min-w-0 flex-1 truncate" title={text}>{text}</span>
	{#if note}<span class="shrink-0 text-xs whitespace-nowrap text-muted-foreground">{note}</span
		>{/if}
	<span class="w-24 shrink-0 text-right">
		<MoneyDisplay
			minor={entry.amount.amount}
			currency={entry.amount.currency}
			{locale}
			class="tabular-nums"
		/>
	</span>
</li>
