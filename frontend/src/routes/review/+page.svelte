<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, onMount, untrack } from 'svelte';
	import FilterBar from '#lib/components/ledger/filter-bar.svelte';
	import { todayIso } from '#lib/format/index.js';
	import { emptyFilter, fromSearchParams, toSearchParams } from '#lib/ledger/filter.js';
	import Segmented from '#lib/components/common/segmented.svelte';
	import { cutFromSearchParams, withCut, type QueueCut } from '#lib/units/queue-cut.js';
	import { UNIT_PARAM } from '#lib/units/address.js';
	import { unitPanel } from '#lib/units/panel-instance.js';
	import NewDataNotice from '#lib/components/common/new-data-notice.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import ReviewQueue from '#lib/components/review/review-queue.svelte';
	import { entryForm } from '#lib/entry-form/controller.svelte.js';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';
	import { ReviewQueueStore } from '#lib/stores/review-queue.svelte.js';
	import { session } from '#lib/stores/session.svelte.js';

	const CUT_OPTIONS: { value: QueueCut; label: string }[] = [
		{ value: 'date', label: 'By date' },
		{ value: 'counterparty', label: 'By counterparty' }
	];
	const queue = new ReviewQueueStore();
	const locale = $derived(session.config?.locale ?? 'en');

	onMount(() => void lookupsStore.ensure());

	// The address is the filter (as the ledger's): the accounts it names are what the queue shows,
	// and a change fetches the queue again, as a refresh does.
	$effect(() => {
		const accounts = fromSearchParams(page.url.search).account_id;
		const cut = cutFromSearchParams(page.url.searchParams);
		untrack(() => void queue.applyView(accounts, cut));
	});

	async function show(account_id: number[], cut: QueueCut = queue.cut) {
		const params = withCut(toSearchParams({ ...emptyFilter(), account_id }), cut);
		// the panel's address survives a filter change
		if (unitPanel.unitId !== null) params.set(UNIT_PARAM, String(unitPanel.unitId));
		const query = params.toString();
		await goto(`${page.url.pathname}${query ? `?${query}` : ''}`, {
			replaceState: true,
			reset: false
		});
	}
	onDestroy(() => queue.dispose());

	// notices of the entry form (a delete) land on this page's line; a created entry opens in the
	// panel and the queue is told through the panel's source, not refreshed
	$effect(() => entryForm.listen({ notify: (text) => (queue.notice = text) }));

	// the line holds one notice: a write's, else the news ("New data — Refresh", never a count:
	// patterns §7), else the lists that did not load
	const stale = $derived(queue.news.stale);
	const notice = $derived(
		queue.notice !== null
			? { text: queue.notice, error: false }
			: !stale && lookupsStore.failed.length > 0
				? {
						text: `Some lists could not be loaded (${lookupsStore.failed.join(', ')}); their names may be missing below.`,
						error: false
					}
				: null
	);
</script>

<svelte:head>
	<title>Review · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<PageHeader
		level={1}
		title="Review"
		description="Units waiting for a decision: check what was proposed, then commit them one at a time."
	/>

	<FilterBar
		accountOnly
		filter={{ ...emptyFilter(), account_id: [...queue.accountIds] }}
		lookups={lookupsStore.lookups}
		{locale}
		today={todayIso(session.config?.timezone ?? 'UTC')}
		baseCurrency={session.config?.base_currency ?? 'EUR'}
		onchange={(next) => show(next.account_id)}
	>
		{#snippet trailing()}
			<Segmented
				label="Pending review cut"
				options={CUT_OPTIONS}
				value={queue.cut}
				onchange={(cut) => show([...queue.accountIds], cut)}
			/>
		{/snippet}
	</FilterBar>

	<NewDataNotice {stale} onrefresh={() => queue.load()} {notice} />

	<ReviewQueue
		store={queue}
		lookups={lookupsStore.lookups}
		{locale}
		today={todayIso(session.config?.timezone ?? 'UTC')}
		onclearfilters={() => show([])}
	/>
</div>
