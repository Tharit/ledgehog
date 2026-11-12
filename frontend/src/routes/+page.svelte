<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import DataAgeCard from '#lib/components/overview/data-age-card.svelte';
	import NetWorthCard from '#lib/components/overview/net-worth-card.svelte';
	import ReviewCard from '#lib/components/overview/review-card.svelte';
	import SavingsCard from '#lib/components/overview/savings-card.svelte';
	import SpendCard from '#lib/components/overview/spend-card.svelte';
	import TopCategoriesCard from '#lib/components/overview/top-categories-card.svelte';
	import { formatLongDate } from '#lib/format/index.js';
	import { describeLoadError } from '#lib/ledger/errors.js';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';
	import { refetchOnChange } from '#lib/stores/new-data.svelte.js';
	import { OverviewStore } from '#lib/stores/overview.svelte.js';
	import { reviewCount } from '#lib/stores/review-count.svelte.js';

	// The landing page (overview.md): a computed view, so it keeps its figures on screen and
	// replaces them when the ledger's change value moves (patterns §7). No primary action.
	const store = new OverviewStore();

	onMount(() => {
		void store.load();
		void lookupsStore.ensure();
	});
	refetchOnChange('ledger', () => void store.load());
	onDestroy(() => store.dispose());

	const overview = $derived(store.overview);
	const locale = $derived(store.locale);
	const failure = $derived(store.error ? describeLoadError(store.error.code) : null);
	// the Review item's own read: the card says what the navigation says
	const counts = $derived(
		reviewCount.known
			? { pendingReview: reviewCount.pendingReview, needsAccount: reviewCount.needsAccount }
			: null
	);
</script>

<svelte:head>
	<title>Overview · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<PageHeader
		level={1}
		title="Overview"
		description={overview ? formatLongDate(overview.as_of, locale) : undefined}
	/>

	{#if store.status === 'error' && failure}
		<ErrorState
			title="The overview could not be loaded"
			message={failure.message}
			onretry={failure.retryable ? () => store.retry() : undefined}
			class="max-w-none items-center p-8 text-center"
		/>
	{:else if overview && overview.data_age.synced.length + overview.data_age.by_hand.length === 0}
		<EmptyState title="No accounts yet" actionLabel="Open Accounts" actionHref="/accounts">
			Add an account to see its balance, and what comes in and goes out, here.
		</EmptyState>
	{:else}
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" data-slot="figure-cards">
			<NetWorthCard netWorth={overview?.net_worth ?? null} {locale} />
			<SavingsCard savings={overview?.savings ?? null} {locale} />
			<SpendCard spend={overview?.spend ?? null} {locale} />
			<ReviewCard {counts} {locale} />
		</div>
		<div class="grid grid-cols-1 gap-4 lg:grid-cols-2" data-slot="half-cards">
			<DataAgeCard dataAge={overview?.data_age ?? null} today={overview?.as_of ?? ''} {locale} />
			<TopCategoriesCard
				report={store.byCategory}
				status={store.categoriesStatus}
				categories={lookupsStore.lookups.categories}
				{locale}
				onretry={() => store.retry()}
			/>
		</div>
	{/if}
</div>
