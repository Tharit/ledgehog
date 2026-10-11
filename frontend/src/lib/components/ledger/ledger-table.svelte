<script lang="ts">
	import ErrorState from '#lib/components/common/error-state.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { formatCount } from '#lib/format/index.js';
	import { describeLoadError } from '#lib/ledger/errors.js';
	import { ledgerKey, moveCursor } from '#lib/ledger/keys.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import type { Entry } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';
	import { rowGrid } from './columns.js';
	import EntryRow from './entry-row.svelte';

	// The list of entries with its cursor and keyboard model (patterns §5). The list is a snapshot
	// (patterns §7): it shows what it was given and never changes under the cursor.
	let {
		entries,
		total,
		status,
		loadingMore = false,
		error = null,
		moreError = null,
		lookups,
		locale = 'en',
		showAccount = true,
		activeFilters = [],
		onclearfilters,
		onretry,
		onloadmore,
		onsearch
	}: {
		entries: readonly Entry[];
		total: number;
		status: 'loading' | 'ready' | 'error';
		loadingMore?: boolean;
		error?: { code: string; message: string } | null;
		moreError?: { code: string; message: string } | null;
		lookups: Lookups;
		locale?: string;
		/** show the account column (several accounts can appear) */
		showAccount?: boolean;
		/** labels of the active filters, for the "nothing matches" state */
		activeFilters?: readonly string[];
		onclearfilters?: () => void;
		onretry?: () => void;
		onloadmore?: () => void;
		/** `/` was pressed: focus the filter bar's text box */
		onsearch?: () => void;
	} = $props();

	let cursorId = $state<number | null>(null);
	let helpOpen = $state(false);
	let container = $state<HTMLElement | null>(null);

	const cursorIndex = $derived(
		cursorId === null ? -1 : entries.findIndex((e) => e.id === cursorId)
	);
	// the currency is written where amounts of several currencies are listed together (patterns §2)
	const showCurrency = $derived(new Set(entries.map((e) => e.amount.currency)).size > 1);

	function moveBy(delta: number) {
		const next = moveCursor(cursorIndex, delta, entries.length);
		cursorId = next < 0 ? null : entries[next].id;
	}

	function onkeydown(event: KeyboardEvent) {
		const action = ledgerKey(event);
		if (action === null) return;
		switch (action) {
			case 'up':
			case 'down':
				event.preventDefault();
				moveBy(action === 'up' ? -1 : 1);
				break;
			case 'open':
				// Enter will open the unit panel; there is none yet
				break;
			case 'escape':
				if (helpOpen) helpOpen = false;
				else if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
				break;
			case 'search':
				event.preventDefault();
				onsearch?.();
				break;
			case 'help':
				event.preventDefault();
				helpOpen = !helpOpen;
				break;
		}
	}

	// the cursor row scrolls into view
	$effect(() => {
		if (cursorId === null || !container) return;
		container
			.querySelector(`[data-entry-id="${cursorId}"]`)
			?.scrollIntoView?.({ block: 'nearest' });
	});

	const failure = $derived(error ? describeLoadError(error.code) : null);
	const moreFailure = $derived(moreError ? describeLoadError(moreError.code) : null);

	const KEYS: [string, string][] = [
		['↑ ↓ / k j', 'Move the cursor'],
		['Enter', 'Open the entry (not built yet)'],
		['/', 'Filter text'],
		['Esc', 'Close this help, leave a field'],
		['?', 'Show or hide this help']
	];
</script>

<svelte:window {onkeydown} />

<section aria-label="Ledger entries" class="relative">
	{#if status === 'error' && entries.length === 0 && failure}
		<ErrorState
			title={failure.title}
			message={failure.message}
			onretry={failure.retryable ? onretry : undefined}
		/>
	{:else if status === 'ready' && entries.length === 0}
		<div class="flex max-w-xl flex-col items-start gap-3 rounded-xl border bg-card p-5 shadow-card">
			{#if activeFilters.length > 0}
				<h2 class="text-base font-semibold">No entries match these filters</h2>
				<p class="text-sm text-muted-foreground">{activeFilters.join(' · ')}</p>
				<Button variant="outline" onclick={onclearfilters}>Clear filters</Button>
			{:else}
				<h2 class="text-base font-semibold">No entries yet</h2>
				<p class="text-sm text-muted-foreground">
					Entries arrive when a bank account is synced, when an export file is uploaded, or when one
					is entered by hand. Start with an account under Accounts, then bring its data in.
				</p>
			{/if}
		</div>
	{:else}
		<div bind:this={container} role="grid" aria-label="Entries" aria-busy={status === 'loading'}>
			<div
				role="row"
				class={cn(
					rowGrid(showAccount),
					'sticky top-0 z-10 h-8 items-center gap-x-3 border-b border-border bg-muted px-3 text-xs font-medium text-muted-foreground'
				)}
			>
				<div role="columnheader">Date</div>
				{#if showAccount}<div role="columnheader">Account</div>{/if}
				<div role="columnheader">Description</div>
				<div role="columnheader">Payee</div>
				<div role="columnheader">Category</div>
				<div role="columnheader">Tags</div>
				<div role="columnheader"><span class="sr-only">Review</span></div>
				<div role="columnheader" class="text-right">Amount</div>
			</div>

			{#if status === 'loading'}
				{#each Array.from({ length: 12 }, (_, n) => n) as i (i)}
					<div
						role="row"
						class={cn(rowGrid(showAccount), 'h-8 items-center gap-x-3 border-b border-border px-3')}
						data-skeleton
					>
						<div role="gridcell"><div class="h-3 w-16 animate-pulse rounded bg-muted"></div></div>
						{#if showAccount}
							<div role="gridcell"><div class="h-3 w-14 animate-pulse rounded bg-muted"></div></div>
						{/if}
						<div role="gridcell">
							<div
								class="h-3 animate-pulse rounded bg-muted"
								style:width={`${55 + ((i * 17) % 40)}%`}
							></div>
						</div>
						<div role="gridcell"><div class="h-3 w-3/4 animate-pulse rounded bg-muted"></div></div>
						<div role="gridcell"><div class="h-3 w-2/3 animate-pulse rounded bg-muted"></div></div>
						<div role="gridcell"></div>
						<div role="gridcell"></div>
						<div role="gridcell">
							<div class="ml-auto h-3 w-14 animate-pulse rounded bg-muted"></div>
						</div>
					</div>
				{/each}
			{:else}
				{#each entries as entry (entry.id)}
					<EntryRow
						{entry}
						{lookups}
						{locale}
						{showAccount}
						{showCurrency}
						cursor={entry.id === cursorId}
						onselect={() => (cursorId = entry.id)}
					/>
				{/each}
			{/if}
		</div>

		{#if status === 'ready'}
			<div class="flex flex-wrap items-center gap-3 py-3 text-xs text-muted-foreground">
				<span>{formatCount(entries.length, locale)} of {formatCount(total, locale)}</span>
				{#if entries.length < total}
					<Button variant="outline" size="sm" onclick={onloadmore} disabled={loadingMore}>
						{loadingMore ? 'Loading…' : 'Load more'}
					</Button>
				{/if}
				{#if moreFailure}
					<Notice role="alert">
						{moreFailure.title}.
						{#if moreFailure.retryable}
							<button type="button" class="underline underline-offset-2" onclick={onloadmore}>
								Try again
							</button>
						{/if}
					</Notice>
				{/if}
				<button
					type="button"
					class="ml-auto underline-offset-2 hover:underline"
					onclick={() => (helpOpen = !helpOpen)}
					aria-expanded={helpOpen}
				>
					Keyboard shortcuts (?)
				</button>
			</div>
		{/if}
	{/if}

	{#if helpOpen}
		<div
			role="region"
			aria-label="Keyboard shortcuts"
			class="absolute top-10 right-3 z-20 w-72 rounded-xl border bg-popover p-4 text-sm text-popover-foreground shadow-md"
		>
			<h2 class="mb-2 text-base font-semibold">Keyboard</h2>
			<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
				{#each KEYS as [keys, what] (keys)}
					<dt><kbd class="rounded-sm bg-muted px-1.5 py-0.5 font-mono text-xs">{keys}</kbd></dt>
					<dd class="text-muted-foreground">{what}</dd>
				{/each}
			</dl>
		</div>
	{/if}
</section>
