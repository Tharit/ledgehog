<script lang="ts">
	import PencilIcon from '@lucide/svelte/icons/pencil';
	import Trash2Icon from '@lucide/svelte/icons/trash-2';
	import { lateArrivalsLabel, recordGap, recordKindLabel } from '#lib/accounts/statement.js';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import RowActions, { type RowAction } from '#lib/components/common/row-actions.svelte';
	import { formatDate } from '#lib/format/index.js';
	import type { StatementRecord } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';
	import { STATEMENT_ROW, STATEMENT_TEMPLATE } from './statement-columns.js';

	// A balance record, a marker row above the rows of its own date (a record is the state at the
	// end of its day): its kind, its date and its balance; where the ledger does not explain it, "expected X ·
	// difference Z"; the anchor says the opening it sets; a reported record with late arrivals says how many. A record that localises the
	// unexplained difference carries a quiet mark. A marker opens no detail: Edit (a manual record)
	// and Delete… are revealed on hover and focus, as on a settings row (patterns §11.3).
	let {
		record,
		investment = false,
		locale = 'en',
		cursor = false,
		localises = false,
		onselect,
		onedit,
		ondelete
	}: {
		record: StatementRecord;
		investment?: boolean;
		locale?: string;
		cursor?: boolean;
		/** one of the reported records that localise the account's unexplained difference */
		localises?: boolean;
		onselect?: () => void;
		onedit?: () => void;
		ondelete?: () => void;
	} = $props();

	const gap = $derived(recordGap(record, { investment, locale }));
	const late = $derived(lateArrivalsLabel(record));
	const name = $derived(`${recordKindLabel(record)} ${formatDate(record.balance_on, locale)}`);
	const primary = $derived<RowAction[]>([
		...(record.record_kind === 'manual'
			? [{ verb: 'Edit', icon: PencilIcon, onselect: () => onedit?.() }]
			: []),
		{ verb: 'Delete…', icon: Trash2Icon, destructive: true, onselect: () => ondelete?.() }
	]);
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_interactive_supports_focus -->
<div
	role="row"
	data-item-key={`record:${record.id}`}
	data-record-id={record.id}
	data-anchor={record.anchor || undefined}
	aria-selected={cursor}
	data-cursor={cursor || undefined}
	class={cn(
		STATEMENT_ROW,
		'group relative h-8 scroll-mt-10 border-b border-border px-3 text-[13px] font-medium',
		cursor ? 'bg-accent' : 'bg-muted/60 hover:bg-row-hover'
	)}
	style:grid-template-columns={STATEMENT_TEMPLATE}
	onclick={() => onselect?.()}
>
	{#if cursor}
		<span class="absolute inset-y-0 left-0 w-0.5 bg-primary" aria-hidden="true"></span>
	{/if}
	<div role="gridcell"><DateDisplay date={record.balance_on} {locale} /></div>
	<div role="gridcell" class="flex min-w-0 items-center gap-2">
		<span class="shrink-0">{recordKindLabel(record)}</span>
		{#if localises}
			<span
				class="size-1.5 shrink-0 rounded-full bg-dim-ochre"
				role="img"
				aria-label="Localises the unexplained difference"
				title="Localises the unexplained difference"
				data-slot="localises"
			></span>
		{/if}
		{#if gap}
			<span class="min-w-0 truncate font-normal text-muted-foreground" data-slot="gap">{gap}</span>
		{/if}
		{#if late}
			<span class="min-w-0 truncate font-normal text-muted-foreground" data-slot="late">{late}</span
			>
		{/if}
		<span class="ml-auto shrink-0"><RowActions {name} {primary} /></span>
	</div>
	<div role="gridcell"></div>
	<div role="gridcell"></div>
	<div role="gridcell">
		<MoneyDisplay
			minor={record.balance.amount}
			currency={record.balance.currency}
			{locale}
			showPlus={false}
		/>
	</div>
</div>
