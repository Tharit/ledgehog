<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, onMount, untrack } from 'svelte';
	import NewDataNotice from '#lib/components/common/new-data-notice.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import DocumentsFilterBar from '#lib/components/documents/documents-filter-bar.svelte';
	import DocumentsTable from '#lib/components/documents/documents-table.svelte';
	import {
		documentFilterFromParams,
		documentSearchParams,
		emptyDocumentFilter
	} from '#lib/documents/filter.js';
	import { changes } from '#lib/stores/changes.svelte.js';
	import { modelLinesLine } from '#lib/units/model-pending.js';
	import { UNIT_PARAM } from '#lib/units/address.js';
	import { unitPanel } from '#lib/units/panel-instance.js';
	import { DocumentsStore } from '#lib/stores/documents.svelte.js';
	import type { DocumentFilter } from '#lib/types/domain.js';

	const documents = new DocumentsStore();

	// The URL is the filter, so a link can be bookmarked and shared: whatever the query string says
	// (first visit, Back, a link from elsewhere) is what the list shows.
	$effect(() => {
		const filter = documentFilterFromParams(page.url.search);
		untrack(() => documents.applyFilter(filter));
	});

	onMount(() => {
		void documents.loadLookups();
		void documents.loadProviders();
	});
	onDestroy(() => documents.dispose());

	async function show(filter: DocumentFilter) {
		const params = documentSearchParams(filter);
		// the panel's address survives a filter change
		if (unitPanel.unitId !== null) params.set(UNIT_PARAM, String(unitPanel.unitId));
		const query = params.toString();
		await goto(`${page.url.pathname}${query ? `?${query}` : ''}`, { replaceState: true });
	}

	const modelLine = $derived(modelLinesLine(changes.modelPendingLines));

	const currencies = $derived([
		...new Set([...documents.lookups.accounts.values()].map((a) => a.currency))
	]);

	// the line holds the news ("New data — Refresh"), else the lists that did not load, so a missing
	// name is explained
	const notice = $derived(
		documents.lookupsFailed.length > 0
			? {
					text: `Some lists could not be loaded (${documents.lookupsFailed.join(', ')}); their names may be missing below.`,
					error: false
				}
			: null
	);
</script>

<svelte:head>
	<title>Documents · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<PageHeader
		level={1}
		title="Documents"
		description="Orders and payment details that explain transactions. They arrive with imports and are linked when a transaction is reviewed."
	/>

	<DocumentsFilterBar
		filter={documents.filter}
		providers={documents.providers}
		{currencies}
		locale={documents.locale}
		today={documents.today}
		baseCurrency={documents.baseCurrency}
		onchange={show}
	/>

	<!-- one reserved line, so a notice appearing never moves the rows (patterns §7) -->
	<NewDataNotice stale={documents.news.stale} onrefresh={() => documents.reload()} {notice} />

	{#if modelLine}
		<p class="text-sm text-muted-foreground" data-slot="model-pending-line">{modelLine}</p>
	{/if}

	<DocumentsTable
		documents={documents.documents}
		total={documents.total}
		status={documents.status}
		loadingMore={documents.loadingMore}
		error={documents.error}
		moreError={documents.moreError}
		locale={documents.locale}
		activeFilters={documents.activeFilters}
		onopen={(id) => goto(`/documents/${id}`)}
		onclearfilters={() => show(emptyDocumentFilter())}
		onretry={() => documents.reload()}
		onloadmore={() => documents.loadMore()}
	/>
</div>
