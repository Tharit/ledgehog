<script lang="ts">
	import Card from '#lib/components/common/card.svelte';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import { ACCOUNT_KINDS } from '#lib/accounts/kinds.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import type { Account } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';
	import AccountFacts from './account-facts.svelte';

	// One row per account (ux/views/account.md): its icon and name, its kind, its balance with the
	// currency code and its facts line. The row opens the account page. Closed accounts are muted.
	// `flush` is the Accounts page's list, a card of its own, rows edge to edge; by default the
	// rows sit inside a padded card of the Overview.
	let {
		accounts,
		locale = 'en',
		today,
		flush = false,
		onadd
	}: {
		/** in the order to show: open accounts first, then the closed ones */
		accounts: readonly Account[];
		locale?: string;
		today: string;
		flush?: boolean;
		onadd?: () => void;
	} = $props();

	// in a flush card the first and last row follow its curve, and the last has no hairline
	const FLUSH_ROW =
		'first:[&>a]:rounded-t-[11px] last:[&>a]:rounded-b-[11px] last:[&>a]:border-b-0';
	const kindLabel = (kind: string) => ACCOUNT_KINDS.find((k) => k.kind === kind)?.label ?? kind;
</script>

{#if accounts.length === 0}
	<EmptyState title="No accounts yet" actionLabel="Add account" onaction={onadd}>
		Accounts are added here and then fed by a file, a sync, or by hand.
	</EmptyState>
{:else}
	{#snippet items()}
		{#each accounts as account (account.id)}
			{@const look = resolveAccount(account)}
			{@const closed = account.closed_on !== null}
			<li
				data-account-id={account.id}
				data-closed={closed || undefined}
				class={flush ? FLUSH_ROW : undefined}
			>
				<a
					href={`/accounts/${account.id}`}
					class={cn(
						'flex min-h-14 items-center gap-3 border-b border-border py-2 outline-none hover:bg-row-hover focus-visible:ring-2 focus-visible:ring-ring',
						flush ? 'px-4' : 'px-1',
						closed && 'text-muted-foreground'
					)}
				>
					<DimensionIcon icon={look.icon} color={look.color} size="comfortable" />
					<span class="flex min-w-0 flex-1 flex-col">
						<span class="truncate text-sm font-medium">{account.name}</span>
						<span class="truncate text-xs text-muted-foreground">
							{kindLabel(account.kind)}{closed ? ' · closed' : ''}
						</span>
					</span>
					<AccountFacts {account} {locale} {today} align="right" />
				</a>
			</li>
		{/each}
	{/snippet}
	{#if flush}
		<Card variant="flush" element="ul" data-slot="account-list" aria-label="Accounts">
			{@render items()}
		</Card>
	{:else}
		<ul class="flex flex-col" data-slot="account-list" aria-label="Accounts">
			{@render items()}
		</ul>
	{/if}
{/if}
