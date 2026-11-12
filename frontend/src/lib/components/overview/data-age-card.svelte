<script lang="ts">
	import AccountList from '#lib/components/accounts/account-list.svelte';
	import type { Overview } from '#lib/reports/types.js';
	import ListCard from './list-card.svelte';

	// The stalest accounts (spec §3.11): the three stalest synced and the three stalest kept by
	// hand, each a short list of the Accounts rows, never fed first, a settled clearance account
	// last. A synced account's age is a lapse, an unsynced one's a chore, so they are not ranked
	// against each other; a list with no accounts is left out. No threshold colours.
	let {
		dataAge,
		today,
		locale = 'en'
	}: { dataAge: Overview['data_age'] | null; today: string; locale?: string } = $props();

	const lists = $derived(
		dataAge
			? [
					{ label: 'Synced', accounts: dataAge.synced },
					{ label: 'By hand', accounts: dataAge.by_hand }
				].filter((list) => list.accounts.length > 0)
			: []
	);
</script>

<ListCard title="Data age" caption="Stalest first">
	{#if !dataAge}
		<div class="h-32 animate-pulse rounded-md bg-muted" data-slot="accounts-skeleton"></div>
	{:else}
		{#each lists as list (list.label)}
			<section class="flex flex-col gap-1" data-list={list.label}>
				<h3 class="text-xs font-medium text-muted-foreground">{list.label}</h3>
				<AccountList accounts={list.accounts} label={list.label} {locale} {today} />
			</section>
		{/each}
		<a
			href="/accounts"
			class="shrink-0 rounded-sm text-sm font-medium text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
			data-slot="all-accounts"
		>
			All {dataAge.accounts === 1 ? '1 account' : `${dataAge.accounts} accounts`} &rarr;
		</a>
	{/if}
</ListCard>
