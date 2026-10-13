<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import NoticeLine from '#lib/components/common/notice-line.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import ReviewQueue from '#lib/components/review/review-queue.svelte';
	import { formatCount } from '#lib/format/index.js';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';
	import { ReviewQueueStore } from '#lib/stores/review-queue.svelte.js';
	import { ruleNames } from '#lib/stores/rule-names.svelte.js';
	import { session } from '#lib/stores/session.svelte.js';

	const queue = new ReviewQueueStore();
	const locale = $derived(session.config?.locale ?? 'en');

	// "N new — refresh" (patterns §7): a passive count, polled on focus and every minute, that
	// refetches only when asked
	const POLL_MS = 60_000;

	onMount(() => {
		void queue.load();
		void lookupsStore.ensure();
		const check = () => void queue.checkNew();
		const timer = setInterval(check, POLL_MS);
		window.addEventListener('focus', check);
		return () => {
			clearInterval(timer);
			window.removeEventListener('focus', check);
		};
	});
	onDestroy(() => queue.dispose());

	const notice = $derived(
		queue.newCount > 0
			? { text: `${formatCount(queue.newCount, locale)} new`, error: false }
			: lookupsStore.failed.length > 0
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

	<NoticeLine {notice}>
		{#snippet action()}
			{#if queue.newCount > 0}
				<ActionButton variant="link" class="h-auto p-0" onclick={() => queue.load()}>
					Refresh
				</ActionButton>
			{/if}
		{/snippet}
	</NoticeLine>

	<ReviewQueue store={queue} lookups={lookupsStore.lookups} rules={ruleNames.names} {locale} />
</div>
