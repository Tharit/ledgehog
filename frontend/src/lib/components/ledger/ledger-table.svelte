<script lang="ts">
	import ErrorState from '#lib/components/common/error-state.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { formatCount } from '#lib/format/index.js';
	import { describeLoadError } from '#lib/ledger/errors.js';
	import { DERIVED_NO_RULE, DERIVED_NOT_TAGGABLE } from '#lib/ledger/errors.js';
	import { ledgerKey, moveCursor } from '#lib/ledger/keys.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { CHANGED_BY_YOU, CHANGED_ELSEWHERE } from '#lib/ledger/patch.js';
	import { isDerivedType } from '#lib/ledger/types.js';
	import type { Entry, Tag } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';
	import { COLUMNS, GRID_TEMPLATE, ROW_GRID } from './columns.js';
	import EntryRow from './entry-row.svelte';
	import TagPicker from './tag-picker.svelte';

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
		activeFilters = [],
		changedIds = new Set<number>(),
		movedIds = new Set<number>(),
		onclearfilters,
		onretry,
		onloadmore,
		onsearch,
		ontoggletag,
		oncreatetag,
		onnotice,
		oncreaterule
	}: {
		entries: readonly Entry[];
		total: number;
		status: 'loading' | 'ready' | 'error';
		loadingMore?: boolean;
		error?: { code: string; message: string } | null;
		moreError?: { code: string; message: string } | null;
		lookups: Lookups;
		locale?: string;
		/** labels of the active filters, for the "nothing matches" state */
		activeFilters?: readonly string[];
		onclearfilters?: () => void;
		onretry?: () => void;
		onloadmore?: () => void;
		/** `/` was pressed: focus the filter bar's text box */
		onsearch?: () => void;
		/** rows the user's tag action took out of the filter: marked, never removed */
		changedIds?: ReadonlySet<number>;
		/** rows a refresh in place did not return: marked too, with another tooltip */
		movedIds?: ReadonlySet<number>;
		/** tag (`tagged`) or untag one entry; true when it worked */
		ontoggletag?: (entryId: number, tagId: number, tagged: boolean) => Promise<boolean>;
		/** create a tag and put it on one entry; true when it worked */
		oncreatetag?: (entryId: number, name: string) => Promise<boolean>;
		/** a quiet one-line message for the page to show */
		onnotice?: (text: string) => void;
		/** start a rule from this entry (`r`, or the row's action) */
		oncreaterule?: (entry: Entry) => void;
	} = $props();

	let cursorId = $state<number | null>(null);
	let helpOpen = $state(false);
	let container = $state<HTMLElement | null>(null);

	const cursorIndex = $derived(
		cursorId === null ? -1 : entries.findIndex((e) => e.id === cursorId)
	);
	// the currency is written where amounts of several currencies are listed together (patterns §2)
	const showCurrency = $derived(new Set(entries.map((e) => e.amount.currency)).size > 1);

	// the tag picker (`t`): tags the ONE entry under the cursor, never the filter's result
	let pickerOpen = $state(false);
	let pickerEntryId = $state<number | null>(null);
	let pickerAnchor = $state<HTMLElement | null>(null);
	let pickerBusy = $state(false);
	const pickerEntry = $derived(
		pickerEntryId === null ? undefined : entries.find((e) => e.id === pickerEntryId)
	);
	const pickerChecked = $derived(new Set(pickerEntry?.tag_ids ?? []));
	const tagList = $derived<Tag[]>([...lookups.tags.values()]);

	function openPicker() {
		if (cursorIndex < 0) return;
		const entry = entries[cursorIndex];
		if (isDerivedType(entry.type)) {
			onnotice?.(DERIVED_NOT_TAGGABLE);
			return;
		}
		pickerEntryId = entry.id;
		pickerAnchor = container?.querySelector<HTMLElement>(`[data-entry-id="${entry.id}"]`) ?? null;
		pickerOpen = true;
	}

	/** Run one tag write; a failure closes the picker so its quiet notice can be read. */
	async function write(run: (entryId: number) => Promise<boolean> | undefined) {
		if (pickerBusy || pickerEntryId === null) return;
		pickerBusy = true;
		try {
			if (!(await run(pickerEntryId))) pickerOpen = false;
		} finally {
			pickerBusy = false;
		}
	}

	// the entry the picker belongs to is gone (the list reloaded)
	$effect(() => {
		if (pickerOpen && !pickerEntry) pickerOpen = false;
	});

	/** `r`: the rule editor, its conditions to be prefilled from the row under the cursor */
	function startRule() {
		if (cursorIndex < 0) return;
		const entry = entries[cursorIndex];
		if (isDerivedType(entry.type)) onnotice?.(DERIVED_NO_RULE);
		else oncreaterule?.(entry);
	}

	function moveBy(delta: number) {
		const next = moveCursor(cursorIndex, delta, entries.length);
		cursorId = next < 0 ? null : entries[next].id;
	}

	/**
	 * Hand the keyboard to the list: leave whatever field has focus, focus the list and put the
	 * cursor on the first row (from the filter box, `↓`). Focus never scrolls the page: only the
	 * cursor row is scrolled into view, and only when it is not visible already.
	 */
	export function enterList() {
		if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
		container?.focus({ preventScroll: true });
		cursorId = entries.length > 0 ? entries[0].id : null;
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
			case 'tag':
				// prevented, so the key is not typed into the picker's search box that opens
				event.preventDefault();
				openPicker();
				break;
			case 'rule':
				event.preventDefault();
				startRule();
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
		['t', 'Tag the row'],
		['r', 'Create a rule from the row'],
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
			class="max-w-none items-center p-8 text-center"
		/>
	{:else if status === 'ready' && entries.length === 0}
		<div
			class="flex w-full flex-col items-center gap-3 rounded-xl border bg-card p-8 text-center shadow-card"
		>
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
		<div
			bind:this={container}
			role="grid"
			tabindex="-1"
			class="outline-none"
			aria-label="Entries"
			aria-busy={status === 'loading'}
		>
			<div
				role="row"
				class={cn(
					ROW_GRID,
					'sticky top-0 z-10 h-8 border-b border-border bg-muted px-3 text-xs font-medium text-muted-foreground'
				)}
				style:grid-template-columns={GRID_TEMPLATE}
			>
				{#each COLUMNS as column (column.id)}
					<div role="columnheader" class={column.align === 'right' ? 'text-right' : undefined}>
						{#if column.hiddenHeader}<span class="sr-only">{column.header}</span
							>{:else}{column.header}{/if}
					</div>
				{/each}
			</div>

			{#if status === 'loading'}
				{#each Array.from({ length: 12 }, (_, n) => n) as i (i)}
					<div
						role="row"
						class={cn(ROW_GRID, 'h-8 border-b border-border px-3')}
						style:grid-template-columns={GRID_TEMPLATE}
						data-skeleton
					>
						{#each COLUMNS as column (column.id)}
							<div role="gridcell">
								{#if column.id === 'description'}
									<div
										class="h-3 animate-pulse rounded bg-muted"
										style:width={`${55 + ((i * 17) % 40)}%`}
									></div>
								{:else if column.id === 'amount'}
									<div class="ml-auto h-3 w-14 animate-pulse rounded bg-muted"></div>
								{:else if column.id !== 'tags' && column.id !== 'review' && column.id !== 'actions'}
									<div class="h-3 w-2/3 animate-pulse rounded bg-muted"></div>
								{/if}
							</div>
						{/each}
					</div>
				{/each}
			{:else}
				{#each entries as entry (entry.id)}
					<EntryRow
						{entry}
						{lookups}
						{locale}
						{showCurrency}
						cursor={entry.id === cursorId}
						changed={changedIds.has(entry.id) || movedIds.has(entry.id)}
						changedTitle={changedIds.has(entry.id) ? CHANGED_BY_YOU : CHANGED_ELSEWHERE}
						onselect={() => (cursorId = entry.id)}
						oncreaterule={oncreaterule ? () => oncreaterule(entry) : undefined}
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

	<TagPicker
		bind:open={pickerOpen}
		anchor={pickerAnchor}
		tags={tagList}
		checked={pickerChecked}
		busy={pickerBusy}
		onselect={(tag) => write((id) => ontoggletag?.(id, tag.id, !pickerChecked.has(tag.id)))}
		oncreate={(name) => write((id) => oncreatetag?.(id, name))}
		onclosefocus={(event) => {
			event.preventDefault();
			container?.focus({ preventScroll: true });
		}}
	/>

	{#if helpOpen}
		<div
			role="region"
			aria-label="Keyboard shortcuts"
			class="fixed right-4 bottom-4 z-50 w-72 max-w-[calc(100vw-2rem)] rounded-xl border bg-popover p-4 text-sm text-popover-foreground shadow-md"
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
