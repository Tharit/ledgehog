<script lang="ts">
	import { duplicateLabel } from '#lib/accounts/statement.js';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import type { StatementSource } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';
	import { STATEMENT_ROW, STATEMENT_TEMPLATE } from './statement-columns.js';

	// One source transaction of the account's statement: booked date, counterparty, purpose, amount
	// and the balance after it. A row entered by hand says so where the counterparty would be; a
	// duplicate is dimmed, has no balance and names the row it duplicates, which a click opens.
	// No action buttons (patterns §11.3): the row opens its detail.
	let {
		row,
		locale = 'en',
		cursor = false,
		onselect,
		onopen,
		onopenoriginal
	}: {
		row: StatementSource;
		locale?: string;
		cursor?: boolean;
		onselect?: () => void;
		onopen?: () => void;
		/** open the row this one duplicates */
		onopenoriginal?: (sourceId: number) => void;
	} = $props();
</script>

<!-- the keyboard is handled for the whole list by the statement table; a click moves the cursor and opens -->
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_interactive_supports_focus -->
<div
	role="row"
	data-item-key={`source:${row.id}`}
	data-source-id={row.id}
	data-duplicate={row.duplicate_of !== null || undefined}
	aria-selected={cursor}
	data-cursor={cursor || undefined}
	class={cn(
		STATEMENT_ROW,
		'relative h-8 scroll-mt-10 border-b border-border px-3 text-[13px]',
		cursor ? 'bg-accent' : 'hover:bg-muted',
		row.duplicate_of !== null && 'text-muted-foreground opacity-70'
	)}
	style:grid-template-columns={STATEMENT_TEMPLATE}
	onclick={(event) => {
		onselect?.();
		if (!(event.target instanceof Element && event.target.closest('button'))) onopen?.();
	}}
>
	{#if cursor}
		<span class="absolute inset-y-0 left-0 w-0.5 bg-primary" aria-hidden="true"></span>
	{/if}
	<div role="gridcell"><DateDisplay date={row.booked_on} {locale} /></div>
	<div role="gridcell" class="flex min-w-0 items-baseline gap-2">
		{#if row.authored}
			<span class="shrink-0 text-muted-foreground italic" data-slot="authored">entered by hand</span
			>
		{:else if row.counterparty_name}
			<span class="min-w-0 shrink truncate" title={row.counterparty_name}>
				{row.counterparty_name}
			</span>
		{/if}
		{#if row.purpose}
			<span class="min-w-0 flex-1 truncate text-muted-foreground" title={row.purpose}>
				{row.purpose}
			</span>
		{/if}
		{#if row.duplicate_of}
			{@const original = row.duplicate_of}
			<button
				type="button"
				tabindex="-1"
				class="shrink-0 rounded-sm text-xs underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring"
				data-slot="duplicate-of"
				onclick={() => onopenoriginal?.(original.id)}
			>
				{duplicateLabel(original, locale)}
			</button>
		{/if}
	</div>
	<div role="gridcell">
		<MoneyDisplay minor={row.amount.amount} currency={row.amount.currency} {locale} />
	</div>
	<div role="gridcell">
		{#if row.balance}
			<MoneyDisplay
				minor={row.balance.amount}
				currency={row.balance.currency}
				{locale}
				showPlus={false}
				class="text-muted-foreground"
			/>
		{/if}
	</div>
</div>
