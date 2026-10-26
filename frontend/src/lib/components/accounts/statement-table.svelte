<script lang="ts">
	import ActionButton from '#lib/components/common/action-button.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import KeyboardHelp, { type HelpGroup } from '#lib/components/common/keyboard-help.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import { cursorAfterRefetch, isInvestment, itemKey } from '#lib/accounts/statement.js';
	import { formatCount } from '#lib/format/index.js';
	import { describeLoadError } from '#lib/ledger/errors.js';
	import { ledgerKey, moveCursor } from '#lib/ledger/keys.js';
	import type { Account, StatementItem, StatementRecord } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';
	import { STATEMENT_COLUMNS, STATEMENT_ROW, STATEMENT_TEMPLATE } from './statement-columns.js';
	import StatementMarker from './statement-marker.svelte';
	import StatementRow from './statement-row.svelte';

	// The account's statement: its source transactions and balance records, newest first, with the
	// cursor and keyboard model of the ledger list (patterns §5): ↑ ↓ move, Enter or `p` open a
	// source row's detail. The list is a snapshot (patterns §7); after the page's own writes the
	// parent hands over fresh rows and the cursor stays on the row it was on, or its neighbour when
	// that row is gone.
	let {
		items,
		total,
		status,
		account,
		loadingMore = false,
		error = null,
		moreError = null,
		locale = 'en',
		onopen,
		onedit,
		ondelete,
		onloadmore,
		onretry
	}: {
		items: readonly StatementItem[];
		total: number;
		status: 'loading' | 'ready' | 'error';
		account: Pick<Account, 'kind' | 'records_since_zero'>;
		loadingMore?: boolean;
		error?: { code: string; message: string } | null;
		moreError?: { code: string; message: string } | null;
		locale?: string;
		/** a source row's detail was asked for (click, Enter, `p`), or the row it duplicates */
		onopen?: (sourceId: number) => void;
		onedit?: (record: StatementRecord) => void;
		ondelete?: (record: StatementRecord) => void;
		onloadmore?: () => void | Promise<void>;
		onretry?: () => void;
	} = $props();

	let cursorKey = $state<string | null>(null);
	let helpOpen = $state(false);
	let container = $state<HTMLElement | null>(null);
	let lastIndex = 0;

	const investment = $derived(isInvestment(account.kind));
	const localising = $derived(new Set(account.records_since_zero ?? []));
	const cursorIndex = $derived(
		cursorKey === null ? -1 : items.findIndex((item) => itemKey(item) === cursorKey)
	);

	// the rows were replaced (a refetch after a write): the cursor stays on its row, or goes to the
	// row now in its place when that one is gone
	$effect(() => {
		if (cursorKey === null || items.length === 0) return;
		if (items.some((item) => itemKey(item) === cursorKey)) return;
		cursorKey = cursorAfterRefetch(items, cursorKey, lastIndex);
	});
	$effect(() => {
		if (cursorIndex >= 0) lastIndex = cursorIndex;
	});
	$effect(() => {
		if (cursorKey === null || !container) return;
		container
			.querySelector(`[data-item-key="${cursorKey}"]`)
			?.scrollIntoView?.({ block: 'nearest' });
	});

	/**
	 * Give the focus back to the list without scrolling to it: what a dialog opened from a row
	 * returns to (patterns §11.2), the page staying exactly where it was.
	 */
	export function focusList() {
		container?.focus({ preventScroll: true });
	}

	/** Hand the keyboard to the list: the cursor goes to the first row. */
	export function enterList() {
		container?.focus({ preventScroll: true });
		if (items.length > 0) cursorKey = itemKey(items[0]);
	}

	function openAt(index: number) {
		const item = items[index];
		if (item?.kind === 'source') onopen?.(item.id);
	}

	function onkeydown(event: KeyboardEvent) {
		const action = ledgerKey(event);
		if (action === null) return;
		// a focused button or link of a row (its Edit, its "duplicate of") acts on its own
		const inControl =
			event.target instanceof Element && event.target.closest('button, a, [role="menu"]') !== null;
		switch (action) {
			case 'up':
			case 'down': {
				if (inControl) return;
				event.preventDefault();
				const next = moveCursor(cursorIndex, action === 'up' ? -1 : 1, items.length);
				cursorKey = next < 0 ? null : itemKey(items[next]);
				break;
			}
			case 'open':
			case 'provenance':
				if (inControl || cursorIndex < 0) return;
				event.preventDefault();
				openAt(cursorIndex);
				break;
			case 'escape':
				if (
					document.activeElement instanceof HTMLElement &&
					container?.contains(document.activeElement)
				)
					document.activeElement.blur();
				break;
		}
	}

	const failure = $derived(error ? describeLoadError(error.code) : null);
	const moreFailure = $derived(moreError ? describeLoadError(moreError.code) : null);

	const HELP: HelpGroup[] = [
		{
			items: [
				{ keys: '↑ ↓ / k j', description: 'Move the cursor' },
				{ keys: 'Enter / p', description: 'Open the row’s detail and provenance' },
				{ keys: 'Esc', description: 'Close this help, leave a field' },
				{ keys: '?', description: 'Show or hide this help' }
			]
		}
	];
</script>

<svelte:window {onkeydown} />

<section aria-label="Statement" class="relative">
	{#if status === 'error' && items.length === 0 && failure}
		<ErrorState
			title="The statement could not be loaded"
			message={failure.message}
			onretry={failure.retryable ? onretry : undefined}
			class="max-w-none items-center p-8 text-center"
		/>
	{:else if status === 'ready' && items.length === 0}
		<EmptyState title="No rows yet">
			Rows arrive when this account is synced, when an export file is uploaded, or when one is
			entered by hand.
		</EmptyState>
	{:else}
		<div
			bind:this={container}
			role="grid"
			tabindex="-1"
			class="outline-none"
			aria-label="Statement rows"
			aria-busy={status === 'loading'}
		>
			<div
				role="row"
				class={cn(
					STATEMENT_ROW,
					'sticky top-0 z-10 h-8 border-b border-border bg-muted px-3 text-xs font-medium text-muted-foreground'
				)}
				style:grid-template-columns={STATEMENT_TEMPLATE}
			>
				{#each STATEMENT_COLUMNS as column (column.id)}
					<div
						role="columnheader"
						class={'align' in column && column.align === 'right' ? 'text-right' : undefined}
					>
						{column.header}
					</div>
				{/each}
			</div>

			{#if status === 'loading'}
				{#each Array.from({ length: 8 }, (_, n) => n) as i (i)}
					<div
						role="row"
						class={cn(STATEMENT_ROW, 'h-8 border-b border-border px-3')}
						style:grid-template-columns={STATEMENT_TEMPLATE}
						data-skeleton
					>
						<div role="gridcell"><div class="h-3 w-2/3 animate-pulse rounded bg-muted"></div></div>
						<div role="gridcell">
							<div
								class="h-3 animate-pulse rounded bg-muted"
								style:width={`${45 + ((i * 17) % 40)}%`}
							></div>
						</div>
						<div role="gridcell"></div>
						<div role="gridcell">
							<div class="ml-auto h-3 w-14 animate-pulse rounded bg-muted"></div>
						</div>
						<div role="gridcell">
							<div class="ml-auto h-3 w-16 animate-pulse rounded bg-muted"></div>
						</div>
					</div>
				{/each}
			{:else}
				{#each items as item (itemKey(item))}
					{#if item.kind === 'record'}
						<StatementMarker
							record={item}
							{investment}
							{locale}
							cursor={itemKey(item) === cursorKey}
							localises={localising.has(item.id)}
							onselect={() => (cursorKey = itemKey(item))}
							onedit={() => onedit?.(item)}
							ondelete={() => ondelete?.(item)}
						/>
					{:else}
						<StatementRow
							row={item}
							{locale}
							cursor={itemKey(item) === cursorKey}
							onselect={() => (cursorKey = itemKey(item))}
							onopen={() => onopen?.(item.id)}
							onopenoriginal={(id) => onopen?.(id)}
						/>
					{/if}
				{/each}
			{/if}
		</div>

		{#if status === 'ready'}
			<div class="flex flex-wrap items-center gap-3 py-3 text-xs text-muted-foreground">
				<span>{formatCount(items.length, locale)} of {formatCount(total, locale)}</span>
				{#if items.length < total}
					<ActionButton
						variant="outline"
						onclick={onloadmore}
						busy={loadingMore}
						busyLabel="Loading…"
					>
						Load more
					</ActionButton>
				{/if}
				{#if moreFailure}
					<Notice role="alert">
						More rows could not be loaded.
						{#snippet action()}
							{#if moreFailure.retryable}
								<ActionButton variant="link" class="h-auto p-0" onclick={onloadmore}>
									Try again
								</ActionButton>
							{/if}
						{/snippet}
					</Notice>
				{/if}
				<KeyboardHelp groups={HELP} bind:open={helpOpen} class="ml-auto" />
			</div>
		{/if}
	{/if}
</section>
