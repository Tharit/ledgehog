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
			empty: 'No transfer is missing an account.'
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
	import { accounts as accountDialog } from '#lib/accounts/controller.svelte.js';
	import NoticeLine from '#lib/components/common/notice-line.svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import KeyboardHelp, { type HelpGroup } from '#lib/components/common/keyboard-help.svelte';
	import EntryRow from '#lib/components/ledger/entry-row.svelte';
	import { COLUMNS, GRID_TEMPLATE, ROW_GRID } from '#lib/components/ledger/columns.js';
	import { formatCount } from '#lib/format/index.js';
	import { ledgerKey, moveCursor } from '#lib/ledger/keys.js';
	import { UNIT_FRAME, unitTotal } from '#lib/ledger/unit-runs.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import type { ReviewQueueStore } from '#lib/stores/review-queue.svelte.js';
	import { describeUnitLoadError } from '#lib/units/describe.js';
	import { unitPanel } from '#lib/units/panel-instance.js';
	import { markOf } from '#lib/units/patch.js';
	import { registerUnitSource } from '#lib/units/sources.js';
	import {
		completableNotice,
		groupHeading,
		unitsOfGroup,
		waitingReason
	} from '#lib/units/queue.js';
	import type { QueueGroup, Unit } from '#lib/units/types.js';
	import { cn } from '#lib/utils.js';

	// The review queue (views/review-queue.md): three sections (pending review, needs an account,
	// waiting), each by date, as headed lists of unit rows. A unit is one block: its entries are
	// joined, both legs of a pair shown. The cursor is on a unit; Enter opens the panel, which then
	// steps through the queue in this order. The queue is a snapshot: it changes only on request.
	let {
		store,
		lookups,
		locale = 'en'
	}: { store: ReviewQueueStore; lookups: Lookups; locale?: string } = $props();

	let cursorId = $state<number | null>(null); // the anchor entry id of the unit under the cursor
	let container = $state<HTMLElement | null>(null);
	let helpOpen = $state(false);
	const HELP: HelpGroup[] = [
		{
			items: [
				{ keys: '↑ ↓ / k j', description: 'Move the cursor over units' },
				{ keys: 'Enter', description: 'Open the unit for review' },
				{ keys: 'Esc', description: 'Close this help, leave a field' },
				{ keys: '?', description: 'Show or hide this help' }
			]
		}
	];
	const template = GRID_TEMPLATE;

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

	/** A section's blocks: the needs-an-account section is one block per currency group (the
	 * server's order; the store keeps the units in that order too, so stepping matches), the others
	 * are one block without a heading. */
	type Block = { key: string; group: QueueGroup | null; units: Unit[] };
	function blocksOf(kind: string, sectionUnits: Unit[], groups: QueueGroup[]): Block[] {
		if (kind !== 'needs_account') return [{ key: kind, group: null, units: sectionUnits }];
		return groups
			.map((group) => ({
				key: `group-${group.currency}`,
				group,
				units: unitsOfGroup(sectionUnits, group.currency)
			}))
			.filter((block) => block.units.length > 0);
	}

	function addAccount(currency: string, event: MouseEvent) {
		accountDialog.openAdd({
			currency,
			kind: 'cash',
			onadded: () => store.noteAccountAdded(currency),
			returnFocus: event.currentTarget instanceof HTMLElement ? event.currentTarget : null
		});
	}

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
		// untracked: the cursor moves, and the store has done the visiting (its `reveal`)
		untrack(() => {
			if (units.some((u) => u.anchor_entry_id === id)) cursorId = id;
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
					{#each blocksOf(section.kind, section.units, section.groups) as block (block.key)}
						{@const heading = block.group
							? groupHeading(block.group.count, block.group.currency, locale)
							: info.title}
						{#if block.group}
							{@const currency = block.group.currency}
							<div class="mt-2 mb-1 flex flex-wrap items-center gap-3" data-group={currency}>
								<h3 class="text-sm font-medium">{heading}</h3>
								<ActionButton
									variant="outline"
									onclick={(event: MouseEvent) => addAccount(currency, event)}
								>
									Add account
								</ActionButton>
							</div>
							{#if store.accountsAdded.includes(currency)}
								<NoticeLine
									notice={{ text: completableNotice(block.group.count, locale), error: false }}
								>
									{#snippet action()}
										<ActionButton variant="link" class="h-auto p-0" onclick={() => store.load()}>
											Refresh
										</ActionButton>
									{/snippet}
								</NoticeLine>
							{/if}
						{/if}
						<div role="grid" aria-label={heading}>
							<div
								role="row"
								class={cn(
									ROW_GRID,
									'h-8 border-b border-border bg-muted px-3 text-xs font-medium text-muted-foreground'
								)}
								style:grid-template-columns={template}
							>
								{#each COLUMNS as column (column.id)}
									<div
										role="columnheader"
										class={column.align === 'right' ? 'text-right' : undefined}
									>
										{#if column.hiddenHeader}<span class="sr-only">{column.header}</span
											>{:else}{column.header}{/if}
									</div>
								{/each}
							</div>
							{#each block.units as unit (unit.anchor_entry_id)}
								<div
									role="rowgroup"
									data-unit={unit.anchor_entry_id}
									class={unit.entries.length > 1 ? UNIT_FRAME : undefined}
								>
									{#each unit.entries as entry (entry.id)}
										{@const mark = markOf(store.marks, entry.id)}
										{@const total = unitTotal(unit.entries)}
										<EntryRow
											joined={unit.entries.length > 1}
											unitTotal={entry.id === unit.entries[0].id ? total : null}
											{entry}
											{lookups}
											{locale}
											{showCurrency}
											cursor={unit.anchor_entry_id === cursorId}
											changed={mark !== undefined && !store.marks.resolved.has(entry.id)}
											changedTitle={mark}
											resolved={store.marks.resolved.has(entry.id)}
											confirmed={store.marks.confirmed.has(entry.id)}
											onselect={() => (cursorId = unit.anchor_entry_id)}
											onopen={() => openUnit(unit)}
											ontags={() => openUnit(unit)}
										/>
									{/each}
									{#if unit.waiting}
										<div role="row" class="border-b border-border px-3 py-1">
											<div
												role="gridcell"
												class="text-xs text-muted-foreground"
												data-slot="waiting-reason"
											>
												{waitingReason(unit.waiting, lookups, locale)}
											</div>
										</div>
									{/if}
								</div>
							{/each}
						</div>
					{/each}
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
