<script lang="ts">
	import { untrack } from 'svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import Card from '#lib/components/common/card.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import KeyboardHelp, { type HelpGroup } from '#lib/components/common/keyboard-help.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import { columnCurrency, formatCount, formatMoney } from '#lib/format/index.js';
	import { describeLoadError } from '#lib/ledger/errors.js';
	import { DERIVED_NOT_TAGGABLE } from '#lib/ledger/errors.js';
	import { ledgerKey, moveCursor } from '#lib/ledger/keys.js';
	import { UNIT_FRAME, unitRuns } from '#lib/ledger/unit-runs.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { CHANGED_BY_YOU, CHANGED_ELSEWHERE } from '#lib/ledger/patch.js';
	import { isDerivedType } from '#lib/ledger/types.js';
	import type { Entry, Money, Tag } from '#lib/types/domain.js';
	import { DERIVED_NOTICE } from '#lib/units/describe.js';
	import { unitPanel } from '#lib/units/panel-instance.js';
	import { markOf, noMarks, type Marks } from '#lib/units/patch.js';
	import { neighbourEntry, registerUnitSource } from '#lib/units/sources.js';
	import type { Affected } from '#lib/units/types.js';
	import { cn } from '#lib/utils.js';
	import { COLUMNS, GRID_TEMPLATE, ROW_GRID, columnHeader } from './columns.js';
	import EntryRow from './entry-row.svelte';
	import TagPicker from './tag-picker.svelte';

	// The list of entries with its cursor and keyboard model (patterns §5). The list is a snapshot
	// (patterns §7): it shows what it was given and never changes under the cursor.
	let {
		entries,
		total,
		sums = [],
		status,
		loadingMore = false,
		error = null,
		moreError = null,
		lookups,
		locale = 'en',
		activeFilters = [],
		changedIds = new Set<number>(),
		movedIds = new Set<number>(),
		marks = noMarks(),
		onclearfilters,
		onretry,
		onloadmore,
		onsearch,
		ontoggletag,
		oncreatetag,
		onnotice,
		onpatch,
		onvisit
	}: {
		entries: readonly Entry[];
		total: number;
		/** the signed sum of every entry matching the filter, per currency, as the server sent it */
		sums?: readonly Money[];
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
		onloadmore?: () => void | Promise<void>;
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
		/** what an action touched in a unit: patch the rows held, in place */
		onpatch?: (affected: Affected) => void;
		/** what the unit panel's actions did to the rows (resolved, consequence, deleted, returned) */
		marks?: Marks;
		/** the cursor visited these rows: their marks fade */
		onvisit?: (entryIds: number[]) => void;
	} = $props();

	let cursorId = $state<number | null>(null);
	let helpOpen = $state(false);
	let container = $state<HTMLElement | null>(null);

	const runs = $derived(unitRuns(entries));
	const cursorIndex = $derived(
		cursorId === null ? -1 : entries.findIndex((e) => e.id === cursorId)
	);
	// the currency is named in the header where the amounts share one, and written in every cell
	// where they mix (patterns §2); the server's sums say what the filter selects, so Load more
	// never relabels. Without sums, the rows held decide.
	const columnCode = $derived(
		sums.length > 0
			? columnCurrency(sums.map((s) => s.currency))
			: columnCurrency(entries.map((e) => e.amount.currency))
	);
	const showCurrency = $derived(
		sums.length > 0 ? sums.length > 1 : columnCode === null && entries.length > 0
	);

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

	// `t`, or a click on a row's tags cell, which puts the cursor on that row first
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

	// The ledger is where the panel steps (`[` `]`): to the next row of ANOTHER unit, the siblings
	// of a split skipped. It knows entries, not units, so it knows no "12 of 214" either.
	let quietId: number | null = null; // the cursor landed here without visiting (units just committed)
	const source = {
		neighbour: (id: number, dir: -1 | 1) => neighbourEntry(entries, id, dir),
		patch: (affected: Affected) => onpatch?.(affected),
		notice: (text: string) => onnotice?.(text),
		// the end of the loaded rows is not the end of the list: load more and carry on
		loadMore: async () => {
			const held = entries.length;
			await onloadmore?.();
			return entries.length > held;
		},
		// the cursor follows the unit the panel shows; the existing effect scrolls the row into view
		reveal: (id: number, visit = true) => {
			if (!entries.some((e) => e.id === id)) return false;
			quietId = visit ? null : id;
			cursorId = id;
			return true;
		}
	};
	$effect(() => registerUnitSource(source));

	/** Enter or a click: open the unit of the row, or say a derived entry has none (patterns §5). */
	function openUnit(entryId: number | null = cursorId) {
		const entry = entries.find((e) => e.id === entryId);
		if (!entry) return;
		if (isDerivedType(entry.type)) {
			onnotice?.(DERIVED_NOTICE);
			return;
		}
		registerUnitSource(source); // the newest list is the one the panel steps through
		unitPanel.open(entry.id, container);
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
				event.preventDefault();
				openUnit();
				break;
			case 'escape':
				// (an open help closes itself first and keeps the key)
				if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
				break;
			case 'search':
				event.preventDefault();
				onsearch?.();
				break;
			case 'tag':
				// prevented, so the key is not typed into the picker's search box that opens
				event.preventDefault();
				openPicker();
				break;
		}
	}

	// a mark fades when the cursor visits the row (patterns §7)
	$effect(() => {
		const id = cursorId;
		const quiet = quietId === id;
		quietId = null;
		if (id !== null && !quiet) untrack(() => onvisit?.([id]));
	});

	// the cursor row scrolls into view
	$effect(() => {
		if (cursorId === null || !container) return;
		container
			.querySelector(`[data-entry-id="${cursorId}"]`)
			?.scrollIntoView?.({ block: 'nearest' });
	});

	const showTotals = $derived(status === 'ready' && entries.length > 0);
	// a figure carries its currency code when the total spans several currencies
	const sumsCoded = $derived(sums.length > 1);
	const totalLabel = $derived(`Total of all ${formatCount(total, locale)}`);
	const totalName = $derived(
		`${totalLabel} entries: ${sums
			.map((sum) =>
				formatMoney(sum.amount, sum.currency, { locale, showCurrency: sumsCoded, showPlus: true })
			)
			.join(', ')}`
	);
	// The footer takes over the card's bottom edge, so the last row's own bottom rounding and
	// divider go (the footer's top border is the divider); without it the old rules stay.
	const LAST_ROW = $derived(
		showTotals
			? '[&>:last-child]:border-b-0 [&>:last-child>:last-child]:border-b-0'
			: '[&>:last-child]:rounded-b-[11px] [&>:last-child]:border-b-0 [&>:last-child>:last-child]:rounded-b-[11px] [&>:last-child>:last-child]:border-b-0'
	);

	// To drop the sticky footer (it stays at the bottom of the view while the list is on screen),
	// empty this one constant.
	const STICKY_FOOTER = 'sticky bottom-0 z-10';

	const failure = $derived(error ? describeLoadError(error.code) : null);
	const moreFailure = $derived(moreError ? describeLoadError(moreError.code) : null);

	const HELP: HelpGroup[] = [
		{
			items: [
				{ keys: '↑ ↓ / k j', description: 'Move the cursor' },
				{ keys: 'Enter', description: 'Open the entry for review' },
				{ keys: 't', description: 'Tag the row' },
				{ keys: '/', description: 'Filter text' },
				{ keys: 'Esc', description: 'Close this help, leave a field' },
				{ keys: '?', description: 'Show or hide this help' }
			]
		}
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
		{#if activeFilters.length > 0}
			<EmptyState
				title="No entries match these filters"
				actionLabel="Clear filters"
				onaction={onclearfilters}
			>
				{activeFilters.join(' · ')}
			</EmptyState>
		{:else}
			<EmptyState title="No entries yet">
				Entries arrive when a bank account is synced, when an export file is uploaded, or when one
				is entered by hand. Start with an account under Accounts, then bring its data in.
			</EmptyState>
		{/if}
	{:else}
		<Card variant="flush">
			<div
				bind:this={container}
				role="grid"
				tabindex="-1"
				class={cn('outline-none', LAST_ROW)}
				aria-label="Entries"
				aria-busy={status === 'loading'}
			>
				<div
					role="row"
					class={cn(
						ROW_GRID,
						'sticky top-0 z-10 h-8 rounded-t-[11px] border-b border-border bg-muted px-3 text-xs font-medium text-muted-foreground'
					)}
					style:grid-template-columns={GRID_TEMPLATE}
				>
					{#each COLUMNS as column (column.id)}
						<div
							role="columnheader"
							class={cn('min-w-0 truncate', column.align === 'right' && 'text-right')}
						>
							{#if column.hiddenHeader}<span class="sr-only">{column.header}</span
								>{:else}{columnHeader(column, columnCode)}{/if}
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
									{:else if column.id !== 'tags' && column.id !== 'review'}
										<div class="h-3 w-2/3 animate-pulse rounded bg-muted"></div>
									{/if}
								</div>
							{/each}
						</div>
					{/each}
				{:else}
					{#each runs as run (run.entries[0].id)}
						{@const joined = run.entries.length > 1}
						{#snippet rows()}
							{#each run.entries as entry (entry.id)}
								{@const mark = markOf(marks, entry.id)}
								<EntryRow
									{entry}
									{lookups}
									{locale}
									{showCurrency}
									modelPending={entry.model_pending}
									cursor={entry.id === cursorId}
									{joined}
									unitCursor={joined &&
										entry.id !== cursorId &&
										run.entries.some((e) => e.id === cursorId)}
									unitTotal={run.total}
									changed={changedIds.has(entry.id) ||
										movedIds.has(entry.id) ||
										(mark !== undefined && !marks.resolved.has(entry.id))}
									changedTitle={mark ??
										(changedIds.has(entry.id) ? CHANGED_BY_YOU : CHANGED_ELSEWHERE)}
									resolved={marks.resolved.has(entry.id)}
									confirmed={marks.confirmed.has(entry.id)}
									onselect={() => (cursorId = entry.id)}
									onopen={() => openUnit(entry.id)}
									ontags={() => {
										cursorId = entry.id;
										openPicker();
									}}
								/>
							{/each}
						{/snippet}
						{#if joined}
							<div role="rowgroup" data-unit={run.key} class={UNIT_FRAME}>{@render rows()}</div>
						{:else}
							{@render rows()}
						{/if}
					{/each}
				{/if}
			</div>
			{#if showTotals}
				<!-- outside the grid: it is a summary of the whole list, not a row of entries -->
				<div
					data-total-row
					class={cn(
						STICKY_FOOTER,
						'flex min-h-8 items-center gap-3 rounded-b-[11px] border-t border-border bg-muted px-3 text-xs font-medium text-muted-foreground'
					)}
				>
					<span class="shrink-0 font-normal">
						{formatCount(entries.length, locale)} of {formatCount(total, locale)} entries
					</span>
					{#if entries.length < total}
						<ActionButton
							variant="outline"
							class="h-6 px-2 text-xs"
							onclick={onloadmore}
							busy={loadingMore}
							busyLabel="Loading…"
						>
							Load more
						</ActionButton>
					{/if}
					{#if moreFailure}
						<Notice role="alert">
							{moreFailure.title}.
							{#snippet action()}
								{#if moreFailure.retryable}
									<ActionButton variant="link" class="h-auto p-0" onclick={onloadmore}>
										Try again
									</ActionButton>
								{/if}
							{/snippet}
						</Notice>
					{/if}
					<KeyboardHelp groups={HELP} bind:open={helpOpen} />
					{#if sums.length > 0}
						<div
							role="group"
							aria-label={totalName}
							class="ml-auto flex shrink-0 items-center gap-3"
						>
							<span aria-hidden="true">{totalLabel}</span>
							{#each sums as sum (sum.currency)}
								<span aria-hidden="true" class="text-[13px] font-normal">
									<MoneyDisplay
										minor={sum.amount}
										currency={sum.currency}
										{locale}
										showCurrency={sumsCoded}
									/>
								</span>
							{/each}
						</div>
					{/if}
				</div>
			{/if}
		</Card>
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
</section>
