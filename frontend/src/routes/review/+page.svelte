<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import NewDataNotice from '#lib/components/common/new-data-notice.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import ReviewQueue from '#lib/components/review/review-queue.svelte';
	import { entryForm } from '#lib/entry-form/controller.svelte.js';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';
	import { ReviewQueueStore } from '#lib/stores/review-queue.svelte.js';
	import { session } from '#lib/stores/session.svelte.js';

	const queue = new ReviewQueueStore();
	const locale = $derived(session.config?.locale ?? 'en');

	onMount(() => {
		void queue.load();
		void lookupsStore.ensure();
	});
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

	<NewDataNotice {stale} onrefresh={() => queue.load()} {notice} />

	<ReviewQueue store={queue} lookups={lookupsStore.lookups} {locale} />
</div>
