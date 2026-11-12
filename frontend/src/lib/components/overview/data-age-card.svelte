<script lang="ts">
	import { describeDataAge } from '#lib/accounts/facts.js';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import type { Overview } from '#lib/reports/types.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import ListCard from './list-card.svelte';

	// The stalest accounts (spec §3.11): the three stalest synced and the three stalest kept by
	// hand, each a short list of rows with the account's icon, name and data age, never fed first, a
	// settled clearance account last. The balance is the accounts list's, not this card's. A synced
	// account's age is a lapse, an unsynced one's a chore, so they are not ranked against each other;
	// a list with no accounts is left out. No threshold colours. The header opens Accounts.
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

<ListCard title="Data age" caption="Stalest first" linkLabel="Accounts" href="/accounts">
	{#if !dataAge}
		<div class="h-32 animate-pulse rounded-md bg-muted" data-slot="accounts-skeleton"></div>
	{:else}
		{#each lists as list (list.label)}
			<section class="flex flex-col gap-1" data-list={list.label}>
				<h3 class="text-xs font-medium text-muted-foreground">{list.label}</h3>
				<ul class="flex flex-col" aria-label={list.label}>
					{#each list.accounts as account (account.id)}
						{@const look = resolveAccount(account)}
						{@const age = describeDataAge(account, { locale, today })}
						<li>
							<a
								href={`/accounts/${account.id}`}
								class="flex min-h-12 items-center gap-3 border-b border-border px-1 py-2 text-sm outline-none last:border-b-0 hover:bg-row-hover focus-visible:ring-2 focus-visible:ring-ring"
								data-account-id={account.id}
							>
								<DimensionIcon icon={look.icon} color={look.color} size="comfortable" />
								<span class="min-w-0 flex-1 truncate font-medium">{account.name}</span>
								<span
									class="shrink-0 text-xs text-muted-foreground"
									title={age.title}
									data-fact="age">{age.text}</span
								>
							</a>
						</li>
					{/each}
				</ul>
			</section>
		{/each}
	{/if}
</ListCard>
