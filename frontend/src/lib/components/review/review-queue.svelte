<script lang="ts" module>
	import type { SectionKind } from '#lib/units/types.js';

	/** The state each section holds (design §6): the glyph of its review token, in the heading slot. */
	const SECTION_TOKEN: Readonly<Record<SectionKind, string>> = {
		pending_review: 'unconfirmed',
		needs_account: 'unmatched_transfer',
		waiting: 'waiting'
	};

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
				'Nothing is waiting. A unit that expects its partner leg appears here until it arrives.'
		}
	};
</script>

<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { REVIEW_BADGE_ICONS } from '#lib/components/common/review-badge.svelte';
	import { accounts as accountDialog } from '#lib/accounts/controller.svelte.js';
	import Card from '#lib/components/common/card.svelte';
	import CardTitle from '#lib/components/common/card-title.svelte';
	import BandRow from '#lib/components/common/band-row.svelte';
	import SubgroupRow from '#lib/components/common/subgroup-row.svelte';
	import NoticeLine from '#lib/components/common/notice-line.svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import KeyboardHelp, { type HelpGroup } from '#lib/components/common/keyboard-help.svelte';
	import EntryRow from '#lib/components/ledger/entry-row.svelte';
	import { ColumnSizer } from '#lib/components/ledger/column-sizer.svelte.js';
	import {
		COLUMNS,
		LEDGER_COLUMNS,
		MEASURABLE,
		ROW_GRID,
		columnHeader,
		gridTemplate
	} from '#lib/components/ledger/columns.js';
	import { changes } from '#lib/stores/changes.svelte.js';
	import { modelQueueLine } from '#lib/units/model-pending.js';
	import {
		columnCurrency,
		formatCount,
		formatDayLabel,
		formatMonthYear,
		todayIso
	} from '#lib/format/index.js';
	import { byMonthAndDay, cutBy, type Cut } from '#lib/ledger/cuts.js';
	import { ledgerKey, moveCursor } from '#lib/ledger/keys.js';
	import { UNIT_FRAME, unitTotal } from '#lib/ledger/unit-runs.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import type { ReviewQueueStore } from '#lib/stores/review-queue.svelte.js';
	import { describeUnitLoadError } from '#lib/units/describe.js';
	import { unitPanel } from '#lib/units/panel-instance.js';
	import { markOf } from '#lib/units/patch.js';
	import { registerUnitSource } from '#lib/units/sources.js';
	import {
		accountKey,
		completableNotice,
		currencyKey,
		groupHeading,
		unitsOfGroup,
		waitingReason
	} from '#lib/units/queue.js';
	import type { CounterpartyGroup, QueueAccountGroup, QueueGroup, Unit } from '#lib/units/types.js';
	import { cn } from '#lib/utils.js';
	import type { Column } from '#lib/components/ledger/columns.js';

	// The review queue (views/review-queue.md): three sections (pending review, needs an account,
	// waiting), each by date, as one flush card each (a title row over the header row), the unit rows
	// beneath. The pending section is cut by month and day into sticky bands, as the ledger list is
	// (design §5), so it has no date column, or by counterparty into one band per counterparty (then
	// it has the date column); the currency and waiting groups of the other two are
	// band rows among their rows, which keep the date column. A unit is one block: its entries
	// are joined, both legs of a pair shown. The cursor is on a unit; Enter opens the panel, which
	// then steps through the queue in this order. The queue is a snapshot: it changes only on
	// request. The columns are as wide as what the rows hold, one set of widths for all sections.
	let {
		store,
		lookups,
		locale = 'en',
		today = todayIso('UTC'),
		onclearfilters
	}: {
		store: ReviewQueueStore;
		lookups: Lookups;
		locale?: string;
		/** the household's today: a day row names the year where it is not this one */
		today?: string;
		/** the account filter is cleared: offered when the filter shows nothing */
		onclearfilters?: () => void;
	} = $props();

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
	// A grid in a flush card: its tinted header and last row follow the card's curve. The last row
	// is a few levels down: the last month, its last day, then a row, or a unit's rowgroup and then
	// its row (the other sections: the last group, then as much).
	const LAST_ROW =
		'[&>:last-child]:rounded-b-[11px] [&>:last-child]:border-b-0 [&>:last-child>:last-child]:rounded-b-[11px] [&>:last-child>:last-child]:border-b-0 [&>:last-child>:last-child>:last-child]:rounded-b-[11px] [&>:last-child>:last-child>:last-child]:border-b-0 [&>:last-child>:last-child>:last-child>:last-child]:rounded-b-[11px] [&>:last-child>:last-child>:last-child>:last-child]:border-b-0';

	// The columns are sized by what the rows of every section hold, and the sections share one set
	// of widths: the allocation is made over all the columns, and the pending section (no date
	// column, its day rows carry the date) takes the same tracks without the date's, the description
	// taking its room. So the columns the sections have in common are equally wide in every card.
	const sizer = new ColumnSizer(() => COLUMNS);
	const templateOf = (kind: SectionKind) => {
		const columns = columnsOf(kind);
		return (
			(store.status === 'ready' ? sizer.templateFor(columns) : undefined) ?? gridTemplate(columns)
		);
	};
	// the pending section has no date column where it is cut by day (the day rows carry the date);
	// cut by counterparty it has one, as the other two sections do
	const byCounterparty = $derived(store.cut === 'counterparty');
	const columnsOf = (kind: SectionKind) =>
		kind === 'pending_review' && !byCounterparty ? LEDGER_COLUMNS : COLUMNS;
	// measure again when the rows held change (load more, filter, refresh, patch) or the amounts'
	// currency is written out
	$effect(() => {
		void store.sections;
		void store.status;
		void store.cut;
		void showCurrency;
		sizer.remeasure();
	});

	// The sticky stack of a section: the header row (2rem), then in the pending section the month
	// band (2.25rem) and the day's band row (1.75rem), in the others the group's band row. Each sticks
	// beneath the one above; the cursor row scrolls to clear them.
	const HEADER_TOP = '2rem';
	const MONTH_TOP = HEADER_TOP;
	const DAY_TOP = '4.25rem';
	const PENDING_OFFSET = '6.5rem';
	const GROUP_OFFSET = '3.75rem';
	const pendingOffset = $derived(byCounterparty ? GROUP_OFFSET : PENDING_OFFSET);

	const units = $derived(store.units);
	const cursorIndex = $derived(
		cursorId === null ? -1 : units.findIndex((u) => u.anchor_entry_id === cursorId)
	);
	const columnCode = $derived(
		columnCurrency(units.flatMap((u) => u.entries.map((e) => e.amount.currency)))
	);
	const showCurrency = $derived(
		new Set(units.flatMap((u) => u.entries.map((e) => e.amount.currency))).size > 1
	);
	// the poll's count, not the snapshot's: the queue itself stays as loaded
	const modelLine = $derived(modelQueueLine(changes.modelPending));
	const failure = $derived(
		store.error ? describeUnitLoadError(store.error.code, 'The review queue') : null
	);

	// the panel steps through this queue; the newest registration is the active one
	onMount(() => registerUnitSource(store.source));

	/** A section's blocks: the needs-an-account section is one block per currency group and the
	 * waiting section one per account waited for (the server's order; the store keeps the units in
	 * that order too, so stepping matches), the other is one block without a heading. */
	type Block = {
		key: string;
		group: QueueGroup | null;
		waitingGroup: QueueAccountGroup | null;
		units: Unit[];
	};
	function blocksOf(
		kind: string,
		sectionUnits: Unit[],
		groups: QueueGroup[],
		accountGroups: QueueAccountGroup[]
	): Block[] {
		const plain = { group: null, waitingGroup: null };
		if (kind === 'needs_account') {
			return groups
				.map((group) => ({
					key: `group-${group.currency}`,
					group,
					waitingGroup: null,
					units: unitsOfGroup(sectionUnits, currencyKey(group.currency))
				}))
				.filter((block) => block.units.length > 0);
		}
		if (kind === 'waiting') {
			return accountGroups
				.map((waitingGroup) => ({
					key: `account-${waitingGroup.account_id}`,
					group: null,
					waitingGroup,
					units: unitsOfGroup(sectionUnits, accountKey(waitingGroup.account_id))
				}))
				.filter((block) => block.units.length > 0);
		}
		return [{ key: kind, ...plain, units: sectionUnits }];
	}

	// a unit is drawn under the day of its first entry, so a band never splits its frame
	const dayBands = (sectionUnits: Unit[]) =>
		cutBy(
			sectionUnits,
			byMonthAndDay(
				(unit) => unit.entries[0].booked_on,
				(date) => formatMonthYear(date, locale),
				(date) => formatDayLabel(date, today, locale)
			)
		);

	// Cut by counterparty: a band is a run of units with one `counterparty_key` (none: "Other"). The
	// label and count are the group's as the first fetch gave them; the server orders the units, so
	// a page boundary only continues the last band.
	const OTHER = '::other';
	const counterpartyBands = (sectionUnits: Unit[], groups: CounterpartyGroup[]) => {
		const byKey = new Map(groups.map((g) => [g.other ? OTHER : (g.key ?? OTHER), g]));
		const cut: Cut<Unit> = {
			key: (unit) => unit.counterparty_key ?? OTHER,
			label: (unit) => byKey.get(unit.counterparty_key ?? OTHER)?.label ?? 'Other'
		};
		return cutBy(sectionUnits, [cut]).map((band) => {
			const group = byKey.get(band.items[0].counterparty_key ?? OTHER);
			return { ...band, count: group ? formatCount(group.count, locale) : undefined };
		});
	};

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

{#snippet unitBlock(unit: Unit, columns: readonly Column[], template: string)}
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
				unitTotal={total}
				modelPending={entry.model_pending}
				{entry}
				{lookups}
				{columns}
				{template}
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
	</div>
{/snippet}

{#if store.status === 'error' && failure}
	<ErrorState
		title={failure.title}
		message={failure.message}
		onretry={failure.retryable ? () => store.load() : undefined}
		class="max-w-none items-center p-8 text-center"
	/>
{:else if store.status === 'ready' && store.total === 0 && store.accountIds.length > 0}
	<EmptyState
		title="No units match these filters"
		actionLabel="Clear filters"
		onaction={onclearfilters}
	>
		{store.accountIds.map((id) => lookups.accounts.get(id)?.name ?? `Account ${id}`).join(' · ')}
	</EmptyState>
{:else if store.status === 'ready' && store.total === 0}
	<EmptyState title="Nothing to review" actionLabel="Open the ledger" actionHref="/ledger">
		Every unit is confirmed. New ones appear here when an account is synced or a file is uploaded.
	</EmptyState>
{:else}
	<div
		bind:this={container}
		tabindex="-1"
		class="flex flex-col gap-4 outline-none"
		aria-busy={store.status === 'loading'}
	>
		{#if modelLine}
			<p class="text-sm text-muted-foreground" data-slot="model-pending-line">{modelLine}</p>
		{/if}
		{#each store.sections as section (section.kind)}
			{@const info = SECTION_INFO[section.kind]}
			{@const SectionIcon = REVIEW_BADGE_ICONS[SECTION_TOKEN[section.kind]]}
			<section aria-labelledby={`section-${section.kind}`} data-section={section.kind}>
				<Card variant="flush">
					<CardTitle
						id={`section-${section.kind}`}
						title={info.title}
						count={formatCount(section.total, locale)}
						icon={SectionIcon}
					/>
					{#if store.status === 'loading'}
						<div role="grid" aria-label={info.title} class={LAST_ROW}>
							{#each [0, 1, 2] as n (n)}
								<div
									role="row"
									class={cn(ROW_GRID, 'h-8 border-b border-border px-3')}
									style:grid-template-columns={templateOf(section.kind)}
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
						<p class="px-3 py-3 text-sm text-muted-foreground" data-slot="section-empty">
							{info.empty}
						</p>
					{:else}
						{@const columns = columnsOf(section.kind)}
						{@const template = templateOf(section.kind)}
						<div
							role="grid"
							aria-label={info.title}
							class={cn(MEASURABLE, LAST_ROW)}
							style:--sticky-offset={section.kind === 'pending_review'
								? pendingOffset
								: GROUP_OFFSET}
							{@attach sizer.attach}
						>
							<div
								role="row"
								class={cn(
									ROW_GRID,
									'sticky top-0 z-10 h-8 border-b border-border bg-muted px-3 text-xs font-medium text-muted-foreground'
								)}
								style:grid-template-columns={template}
							>
								{#each columns as column (column.id)}
									<div
										role="columnheader"
										data-col={column.id}
										class={cn('min-w-0 truncate', column.align === 'right' && 'text-right')}
									>
										{#if column.hiddenHeader}<span class="sr-only">{column.header}</span
											>{:else}{columnHeader(column, columnCode)}{/if}
									</div>
								{/each}
							</div>
							{#if section.kind === 'pending_review' && byCounterparty}
								{#each counterpartyBands(section.units, section.counterpartyGroups) as band, at (`${band.key}#${at}`)}
									<!-- the band's rows in their own element: it ends the band's sticking -->
									<div role="presentation" data-counterparty={band.key}>
										<BandRow label={band.label} count={band.count} top={HEADER_TOP} />
										{#each band.items as unit (unit.anchor_entry_id)}
											{@render unitBlock(unit, columns, template)}
										{/each}
									</div>
								{/each}
							{:else if section.kind === 'pending_review'}
								{#each dayBands(section.units) as month (month.key)}
									<!-- each band's rows in their own element: it ends the band's sticking -->
									<div role="presentation" data-month={month.key}>
										<SubgroupRow label={month.label} top={MONTH_TOP} data-slot="month-row" />
										{#each month.bands as day (day.key)}
											<div role="presentation" data-day={day.key}>
												<BandRow label={day.label} top={DAY_TOP} />
												{#each day.items as unit (unit.anchor_entry_id)}
													{@render unitBlock(unit, columns, template)}
												{/each}
											</div>
										{/each}
									</div>
								{/each}
							{:else}
								{#each blocksOf(section.kind, section.units, section.groups, section.accountGroups) as block (block.key)}
									<!-- the group's rows in their own element: it ends the band row's sticking -->
									<div role="presentation" data-block={block.key}>
										{#if block.group}
											{@const currency = block.group.currency}
											<BandRow
												label={groupHeading(block.group.count, currency, locale)}
												top={HEADER_TOP}
												data-group={currency}
											>
												{#snippet action()}
													<ActionButton
														variant="outline"
														class="h-6 px-2 text-xs"
														onclick={(event: MouseEvent) => addAccount(currency, event)}
													>
														Add account
													</ActionButton>
												{/snippet}
												{#if store.accountsAdded.includes(currency)}
													<NoticeLine
														notice={{
															text: completableNotice(block.group.count, locale),
															error: false
														}}
													>
														{#snippet action()}
															<ActionButton
																variant="link"
																class="h-auto p-0"
																onclick={() => store.load()}
															>
																Refresh
															</ActionButton>
														{/snippet}
													</NoticeLine>
												{/if}
											</BandRow>
										{:else if block.waitingGroup}
											<BandRow
												label={waitingReason(block.waitingGroup, lookups, locale)}
												top={HEADER_TOP}
												data-group-account={block.waitingGroup.account_id}
											/>
										{/if}
										{#each block.units as unit (unit.anchor_entry_id)}
											{@render unitBlock(unit, columns, template)}
										{/each}
									</div>
								{/each}
							{/if}
						</div>
					{/if}
				</Card>
				{#if store.status !== 'loading' && section.units.length > 0}
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
