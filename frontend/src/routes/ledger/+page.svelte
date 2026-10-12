<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, onMount, untrack } from 'svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import FilterBar from '#lib/components/ledger/filter-bar.svelte';
	import LedgerTable from '#lib/components/ledger/ledger-table.svelte';
	import TagAll from '#lib/components/ledger/tag-all.svelte';
	import {
		emptyFilter,
		fromSearchParams,
		toSearchParams,
		type LedgerFilterState
	} from '#lib/ledger/filter.js';
	import { newRuleUrl } from '#lib/rules/prefill.js';
	import { LedgerStore } from '#lib/stores/ledger.svelte.js';

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

	async function show(filter: LedgerFilterState) {
		const query = toSearchParams(filter).toString();
		const typing = document.activeElement === searchEl;
		await goto(`${page.url.pathname}${query ? `?${query}` : ''}`, { replaceState: true });
		// a navigation moves focus to the page; typing in the filter box goes on
		if (typing) searchEl?.focus({ preventScroll: true });
	}

	function focusSearch() {
		searchEl?.focus({ preventScroll: true });
		searchEl?.select();
	}
</script>

<svelte:head>
	<title>Ledger · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<h1 class="text-[28px] font-semibold">Ledger</h1>

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
	<div class="flex min-h-5 flex-col gap-1">
		{#if ledger.notice}
			<Notice role={ledger.notice.error ? 'alert' : 'status'}>{ledger.notice.text}</Notice>
		{/if}
		{#if ledger.lookupsFailed.length > 0}
			<Notice>
				Some lists could not be loaded ({ledger.lookupsFailed.join(', ')}); their names may be
				missing below.
			</Notice>
		{/if}
	</div>

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
		oncreaterule={(entry) => goto(newRuleUrl(entry))}
	/>
</div>
