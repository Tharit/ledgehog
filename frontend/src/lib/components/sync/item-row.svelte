<script lang="ts">
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import RunSummary from '#lib/components/importers/run-summary.svelte';
	import { formatDate } from '#lib/format/index.js';
	import type { TaskItem } from '#lib/sync/events.js';
	import { itemRun, itemSummary, type AccountInfo } from '#lib/sync/progress.js';
	import { cn } from '#lib/utils.js';

	// One row of a login's card (ux/views/sync.md "Progress and report"): the account, or
	// "Documents", and where its run stands: waiting, fetching from a date, waiting for your input,
	// done with what it did, failed with the server's message, or not fetched. A done row opens the
	// run summary, a report: it opens no dialog and colours nothing red (patterns §8).
	let {
		item,
		instanceId,
		account = null,
		waiting = false,
		locale = 'en'
	}: {
		item: TaskItem;
		instanceId: number;
		/** the account of the row; null for a documents row or an account the page does not know */
		account?: AccountInfo | null;
		/** the open prompt belongs to this row's run */
		waiting?: boolean;
		locale?: string;
	} = $props();

	let open = $state(false);
	const isDocuments = $derived(item.kind === 'documents');
	const label = $derived(
		isDocuments ? 'Documents' : (account?.name ?? `Account ${item.accountId}`)
	);
	const stateText = $derived.by(() => {
		switch (item.state) {
			case 'queued':
				return 'Waiting';
			case 'fetching':
				return waiting
					? 'Waiting for your input'
					: item.since
						? `Fetching from ${formatDate(item.since, locale)}…`
						: 'Fetching…';
			case 'done':
				return `Done · ${itemSummary(item)}`;
			case 'failed':
				return 'Failed';
			case 'not_fetched':
				return 'Not fetched';
		}
	});
</script>

<li class="flex flex-col" data-slot="item-row" data-state={item.state}>
	<div class="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-[13px]">
		{#if item.state === 'done'}
			<button
				type="button"
				class="flex min-w-0 flex-1 items-center gap-2 rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
				aria-expanded={open}
				aria-label={`${label}, ${stateText}`}
				onclick={() => (open = !open)}
			>
				<ChevronRightIcon
					size={14}
					strokeWidth={1.75}
					class={cn('shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')}
					aria-hidden="true"
				/>
				{@render name()}
				<span class="min-w-0 truncate text-muted-foreground" data-slot="item-state"
					>{stateText}</span
				>
			</button>
		{:else}
			<span class="flex min-w-0 flex-1 items-center gap-2 pl-5">
				{@render name()}
				<span class="min-w-0 truncate text-muted-foreground" data-slot="item-state"
					>{stateText}</span
				>
			</span>
		{/if}
	</div>
	{#if item.state === 'failed' && item.failure}
		<p class="pb-1.5 pl-5 text-xs text-muted-foreground" data-slot="item-error">
			{item.failure.message}
		</p>
	{/if}
	{#if open && item.state === 'done'}
		<div class="pb-3 pl-5">
			<RunSummary run={itemRun(instanceId, item)} currency={account?.currency ?? ''} {locale} />
		</div>
	{/if}
</li>

{#snippet name()}
	{#if isDocuments || !account}
		<span class="font-medium">{label}</span>
	{:else}
		<span class="font-medium"><AccountDot name={label} color={account.color} /></span>
	{/if}
{/snippet}
