<script lang="ts">
	import Card from '#lib/components/common/card.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import type { Account } from '#lib/types/domain.js';
	import AccountRow from './account-row.svelte';

	// One row per account (ux/views/account.md), as a list of its own: the Overview's Data age card
	// lists the stalest accounts so. `flush` is a card of its own, rows edge to edge; by default the
	// rows sit inside a padded card of the Overview.
	let {
		accounts,
		locale = 'en',
		today,
		flush = false,
		label = 'Accounts',
		onadd
	}: {
		/** in the order to show */
		accounts: readonly Account[];
		locale?: string;
		today: string;
		flush?: boolean;
		/** the list's accessible name */
		label?: string;
		onadd?: () => void;
	} = $props();

	// in a flush card the first and last row follow its curve, and the last has no hairline
	const FLUSH_ROW =
		'first:[&>a]:rounded-t-[11px] last:[&>a]:rounded-b-[11px] last:[&>a]:border-b-0';
</script>

{#if accounts.length === 0}
	<EmptyState title="No accounts yet" actionLabel="Add account" onaction={onadd}>
		Accounts are added here and then fed by a file, a sync, or by hand.
	</EmptyState>
{:else}
	{#snippet items()}
		{#each accounts as account (account.id)}
			<li class={flush ? FLUSH_ROW : undefined}>
				<AccountRow {account} {locale} {today} {flush} />
			</li>
		{/each}
	{/snippet}
	{#if flush}
		<Card variant="flush" element="ul" data-slot="account-list" aria-label={label}>
			{@render items()}
		</Card>
	{:else}
		<ul class="flex flex-col" data-slot="account-list" aria-label={label}>
			{@render items()}
		</ul>
	{/if}
{/if}
