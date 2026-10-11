<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, onMount, untrack } from 'svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import FilterBar from '#lib/components/ledger/filter-bar.svelte';
	import LedgerTable from '#lib/components/ledger/ledger-table.svelte';
	import {
		emptyFilter,
		fromSearchParams,
		toSearchParams,
		type LedgerFilterState
	} from '#lib/ledger/filter.js';
	import { LedgerStore } from '#lib/stores/ledger.svelte.js';

	const ledger = new LedgerStore();
	let searchEl = $state<HTMLInputElement | null>(null);

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
		if (typing) searchEl?.focus();
	}

	function focusSearch() {
		searchEl?.focus();
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
		onchange={show}
	/>

	{#if ledger.lookupsFailed.length > 0}
		<Notice>
			Some lists could not be loaded ({ledger.lookupsFailed.join(', ')}); their names may be missing
			below.
		</Notice>
	{/if}

	<LedgerTable
		entries={ledger.entries}
		total={ledger.total}
		status={ledger.status}
		loadingMore={ledger.loadingMore}
		error={ledger.error}
		moreError={ledger.moreError}
		lookups={ledger.lookups}
		locale={ledger.locale}
		showAccount={ledger.showAccount}
		activeFilters={ledger.activeFilters}
		onclearfilters={() => show(emptyFilter())}
		onretry={() => ledger.reload()}
		onloadmore={() => ledger.loadMore()}
		onsearch={focusSearch}
	/>
</div>
