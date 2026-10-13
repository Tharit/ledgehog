<script lang="ts" module>
	import type { SectionKind } from '#lib/units/types.js';

	/** What each section is called and what its empty state says (views/review-queue.md). */
	export const SECTION_INFO: Readonly<Record<SectionKind, { title: string; empty: string }>> = {
		pending_review: {
			title: 'Pending review',
			empty: 'Nothing here is waiting for a decision.'
		},
		needs_account: {
			title: 'Needs an account',
			empty:
				'No transfer is missing an account. A transfer whose counter account does not exist yet appears here.'
		},
		waiting: {
			title: 'Waiting',
			empty:
				'Nothing is waiting. A unit that expects its partner leg or a document appears here until it arrives.'
		}
	};
</script>

<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import KeyboardHelp, { type HelpGroup } from '#lib/components/common/keyboard-help.svelte';
	import EntryRow from '#lib/components/ledger/entry-row.svelte';
	import { gridTemplate, QUEUE_COLUMNS, ROW_GRID } from '#lib/components/ledger/columns.js';
	import { formatCount } from '#lib/format/index.js';
	import { ledgerKey, moveCursor } from '#lib/ledger/keys.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import type { ReviewQueueStore } from '#lib/stores/review-queue.svelte.js';
	import { describeUnitLoadError } from '#lib/units/describe.js';
	import { rowBasis, type RuleNames } from '#lib/units/evidence.js';
	import { unitPanel } from '#lib/units/panel-instance.js';
	import { markOf } from '#lib/units/patch.js';
	import { registerUnitSource } from '#lib/units/sources.js';
	import type { Unit } from '#lib/units/types.js';
	import { cn } from '#lib/utils.js';

	// The review queue (views/review-queue.md): three sections (pending review, needs an account,
	// waiting), each by date, as headed lists of unit rows. A unit is one block: its entries are
	// joined, both legs of a pair shown, and the basis of what is proposed stands in the last
	// column, proposals italic. The cursor is on a unit; Enter opens the panel, which then steps
	// through the queue in this order. The queue is a snapshot: it changes only on request.
	let {
		store,
		lookups,
		rules,
		locale = 'en'
	}: { store: ReviewQueueStore; lookups: Lookups; rules: RuleNames; locale?: string } = $props();

	let cursorId = $state<number | null>(null); // the anchor entry id of the unit under the cursor
	let container = $state<HTMLElement | null>(null);
	let helpOpen = $state(false);
	const HELP: HelpGroup[] = [
		{
			items: [
				{ keys: '↑ ↓ / k j', description: 'Move the cursor over units' },
				{ keys: 'Enter', description: 'Open the unit for review' },
				{ keys: '[ ]', description: 'In the panel: previous or next unit' },
				{ keys: 'Esc', description: 'Close this help, leave a field' },
				{ keys: '?', description: 'Show or hide this help' }
			]
		}
	];
	const template = gridTemplate(QUEUE_COLUMNS);

	const units = $derived(store.units);
	const cursorIndex = $derived(
		cursorId === null ? -1 : units.findIndex((u) => u.anchor_entry_id === cursorId)
	);
	const showCurrency = $derived(
		new Set(units.flatMap((u) => u.entries.map((e) => e.amount.currency))).size > 1
	);
	const failure = $derived(
		store.error ? describeUnitLoadError(store.error.code, 'The review queue') : null
	);

	// the panel steps through this queue; the newest registration is the active one
	onMount(() => registerUnitSource(store.source));

	function moveTo(index: number) {
		if (index < 0) {
			cursorId = null;
			return;
		}
		const unit = units[index];
		cursorId = unit.anchor_entry_id;
		store.visited(unit.entries.map((e) => e.id)); // a mark fades when the cursor visits
	}

	function openUnit(unit: Unit) {
		cursorId = unit.anchor_entry_id;
		registerUnitSource(store.source);
		unitPanel.open(unit.anchor_entry_id, container);
	}

	function onkeydown(event: KeyboardEvent) {
		const action = ledgerKey(event);
		if (action === null) return;
		switch (action) {
			case 'up':
			case 'down':
				event.preventDefault();
				moveTo(moveCursor(cursorIndex, action === 'up' ? -1 : 1, units.length));
				break;
			case 'open':
				if (cursorIndex >= 0) {
					event.preventDefault();
					openUnit(units[cursorIndex]);
				}
				break;
			case 'escape':
				if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
				break;
		}
	}

	// the cursor follows the unit the panel shows (stepping, opening by address)
	$effect(() => {
		const id = store.revealed;
		if (id === null) return;
		// untracked: moving the cursor reads and writes the store's marks, which must not re-run this
		untrack(() => {
			const unit = units.find((u) => u.anchor_entry_id === id);
			if (!unit) return;
			cursorId = id;
			store.visited(unit.entries.map((e) => e.id));
		});
	});

	// the cursor unit scrolls into view
	$effect(() => {
		if (cursorId === null || !container) return;
		container.querySelector(`[data-unit="${cursorId}"]`)?.scrollIntoView?.({ block: 'nearest' });
	});
</script>

<svelte:window {onkeydown} />

{#if store.status === 'error' && failure}
	<ErrorState
		title={failure.title}
		message={failure.message}
		onretry={failure.retryable ? () => store.load() : undefined}
		class="max-w-none items-center p-8 text-center"
	/>
{:else if store.status === 'ready' && store.total === 0}
	<EmptyState title="Nothing to review" actionLabel="Open the ledger" actionHref="/ledger">
		Every unit is confirmed. New ones appear here when an account is synced or a file is uploaded.
	</EmptyState>
{:else}
	<div
		bind:this={container}
		tabindex="-1"
		class="flex flex-col gap-6 outline-none"
		aria-busy={store.status === 'loading'}
	>
		{#each store.sections as section (section.kind)}
			{@const info = SECTION_INFO[section.kind]}
			<section aria-labelledby={`section-${section.kind}`} data-section={section.kind}>
				<h2 id={`section-${section.kind}`} class="mb-2 text-base font-semibold">
					{info.title}
					<span class="font-normal text-muted-foreground" data-slot="section-count">
						({formatCount(section.total, locale)})
					</span>
				</h2>

				{#if store.status === 'loading'}
					<div role="grid" aria-label={info.title}>
						{#each [0, 1, 2] as n (n)}
							<div
								role="row"
								class={cn(ROW_GRID, 'h-8 border-b border-border px-3')}
								style:grid-template-columns={template}
								data-skeleton
							>
								<div role="gridcell" class="col-span-full">
									<div
										class="h-3 animate-pulse rounded bg-muted"
										style:width={`${50 + ((n * 17) % 40)}%`}
									></div>
								</div>
							</div>
						{/each}
					</div>
				{:else if section.units.length === 0}
					<p class="text-sm text-muted-foreground" data-slot="section-empty">{info.empty}</p>
				{:else}
					<div role="grid" aria-label={info.title}>
						<div
							role="row"
							class={cn(
								ROW_GRID,
								'h-8 border-b border-border bg-muted px-3 text-xs font-medium text-muted-foreground'
							)}
							style:grid-template-columns={template}
						>
							{#each QUEUE_COLUMNS as column (column.id)}
								<div
									role="columnheader"
									class={column.align === 'right' ? 'text-right' : undefined}
								>
									{#if column.hiddenHeader}<span class="sr-only">{column.header}</span
										>{:else}{column.header}{/if}
								</div>
							{/each}
						</div>
						{#each section.units as unit (unit.anchor_entry_id)}
							<div
								role="rowgroup"
								data-unit={unit.anchor_entry_id}
								class={cn(unit.entries.length > 1 && 'border-l-2 border-l-primary/30')}
							>
								{#each unit.entries as entry (entry.id)}
									{@const mark = markOf(store.marks, entry.id)}
									<EntryRow
										{entry}
										{lookups}
										{locale}
										{showCurrency}
										columns={QUEUE_COLUMNS}
										basis={rowBasis(entry, rules, locale)}
										cursor={unit.anchor_entry_id === cursorId}
										changed={mark !== undefined && !store.marks.resolved.has(entry.id)}
										changedTitle={mark}
										resolved={store.marks.resolved.has(entry.id)}
										onselect={() => (cursorId = unit.anchor_entry_id)}
										onopen={() => openUnit(unit)}
										ontags={() => openUnit(unit)}
									/>
								{/each}
							</div>
						{/each}
					</div>
					<div class="flex flex-wrap items-center gap-3 py-2 text-xs text-muted-foreground">
						<span>
							{formatCount(section.units.length, locale)} of {formatCount(section.total, locale)}
						</span>
						{#if section.nextCursor !== null}
							<ActionButton
								variant="outline"
								onclick={() => store.loadMore(section.kind)}
								busy={section.loadingMore}
								busyLabel="Loading…"
							>
								Load more
							</ActionButton>
						{/if}
						{#if section.moreError}
							<span role="alert">
								More could not be loaded.
								<ActionButton
									variant="link"
									class="h-auto p-0"
									onclick={() => store.loadMore(section.kind)}
								>
									Try again
								</ActionButton>
							</span>
						{/if}
					</div>
				{/if}
			</section>
		{/each}
		<div class="flex text-xs text-muted-foreground">
			<KeyboardHelp groups={HELP} bind:open={helpOpen} class="ml-auto" />
		</div>
	</div>
{/if}
