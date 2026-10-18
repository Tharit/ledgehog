<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, onMount, untrack } from 'svelte';
	import NewDataNotice from '#lib/components/common/new-data-notice.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import FilterBar from '#lib/components/ledger/filter-bar.svelte';
	import LedgerTable from '#lib/components/ledger/ledger-table.svelte';
	import TagAll from '#lib/components/ledger/tag-all.svelte';
	import {
		emptyFilter,
		fromSearchParams,
		toSearchParams,
		type LedgerFilterState
	} from '#lib/ledger/filter.js';
	import { entryForm } from '#lib/entry-form/controller.svelte.js';
	import { LedgerStore } from '#lib/stores/ledger.svelte.js';
	import { unitPanel } from '#lib/units/panel-instance.js';
	import { UNIT_PARAM } from '#lib/units/address.js';
	import { activeUnitSource } from '#lib/units/sources.js';

	const ledger = new LedgerStore();
	let searchEl = $state<HTMLInputElement | null>(null);
	let table = $state<ReturnType<typeof LedgerTable> | null>(null);

	// The URL is the filter, so a ledger link can be bookmarked and shared: whatever the query
	// string says (first visit, Back, a link from elsewhere) is what the list shows.
	$effect(() => {
		const filter = fromSearchParams(page.url.search);
		untrack(() => ledger.applyFilter(filter));
	});

	onMount(() => void ledger.loadLookups());
	onDestroy(() => ledger.dispose());

	// The ledger is a snapshot: a transaction entered here is not inserted at its sorted place (that
	// depends on the filter and the sort); the first page is fetched again and the cursor goes to
	// the new row. Notices of the entry form (a delete) land on this page's line.
	$effect(() =>
		entryForm.listen({
			created: async (out) => {
				await ledger.reload();
				if (out.anchor_entry_id !== null) activeUnitSource()?.reveal?.(out.anchor_entry_id);
			},
			notify: (text, error) => ledger.notify(text, error)
		})
	);

	async function show(filter: LedgerFilterState) {
		const params = toSearchParams(filter);
		// the panel's address survives a filter change
		if (unitPanel.unitId !== null) params.set(UNIT_PARAM, String(unitPanel.unitId));
		const query = params.toString();
		const typing = document.activeElement === searchEl;
		await goto(`${page.url.pathname}${query ? `?${query}` : ''}`, { replaceState: true });
		// a navigation moves focus to the page; typing in the filter box goes on
		if (typing) searchEl?.focus({ preventScroll: true });
	}

	// the line holds one notice: a write's, else the lists that did not load
	const notice = $derived(
		ledger.notice ??
			(ledger.lookupsFailed.length > 0
				? {
						text: `Some lists could not be loaded (${ledger.lookupsFailed.join(', ')}); their names may be missing below.`,
						error: false
					}
				: null)
	);

	function focusSearch() {
		searchEl?.focus({ preventScroll: true });
		searchEl?.select();
	}
</script>

<svelte:head>
	<title>Ledger · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<PageHeader
		level={1}
		title="Ledger"
		description="Every entry across your accounts. Narrow it with the filters, then tag the rows by key or all at once."
		actionLabel="Add entry"
		onaction={() => entryForm.openAdd({ filtered: ledger.filter.account_id })}
	/>

	<FilterBar
		filter={ledger.filter}
		lookups={ledger.lookups}
		locale={ledger.locale}
		today={ledger.today}
		baseCurrency={ledger.baseCurrency}
		bind:searchEl
		ondown={() => table?.enterList()}
		onchange={show}
	>
		{#snippet trailing()}
			<TagAll
				flow={ledger.tagAll}
				lookups={ledger.lookups}
				locale={ledger.locale}
				reason={ledger.tagAllReason}
			/>
		{/snippet}
	</FilterBar>

	<!-- one reserved line, so a notice appearing never moves the rows (patterns §7) -->
	<NewDataNotice stale={ledger.news.stale} onrefresh={() => ledger.reload()} {notice} />

	<LedgerTable
		bind:this={table}
		entries={ledger.entries}
		total={ledger.total}
		status={ledger.status}
		loadingMore={ledger.loadingMore}
		error={ledger.error}
		moreError={ledger.moreError}
		lookups={ledger.lookups}
		locale={ledger.locale}
		activeFilters={ledger.activeFilters}
		onclearfilters={() => show(emptyFilter())}
		onretry={() => ledger.reload()}
		onloadmore={() => ledger.loadMore()}
		onsearch={focusSearch}
		changedIds={ledger.changedIds}
		movedIds={ledger.movedIds}
		ontoggletag={(entryId, tagId, tagged) => ledger.setEntryTag(entryId, tagId, tagged)}
		oncreatetag={(entryId, name) => ledger.createTagFor(entryId, name)}
		onnotice={(text) => ledger.notify(text)}
		onpatch={(affected) => ledger.patchAffected(affected)}
		marks={ledger.marks}
		onvisit={(ids) => ledger.visited(ids)}
	/>
</div>
