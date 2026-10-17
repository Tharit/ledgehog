<script lang="ts">
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import { ACCOUNT_KINDS } from '#lib/accounts/kinds.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import type { Account } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';
	import AccountFacts from './account-facts.svelte';

	// One row per account (ux/views/account.md): its icon and name, its kind, its balance with the
	// currency code and its facts line. The row opens the account page. Closed accounts are muted.
	let {
		accounts,
		locale = 'en',
		today,
		onadd
	}: {
		/** in the order to show: open accounts first, then the closed ones */
		accounts: readonly Account[];
		locale?: string;
		today: string;
		onadd?: () => void;
	} = $props();

	const kindLabel = (kind: string) => ACCOUNT_KINDS.find((k) => k.kind === kind)?.label ?? kind;
</script>

{#if accounts.length === 0}
	<EmptyState title="No accounts yet" actionLabel="Add account" onaction={onadd}>
		Accounts are added here and then fed by a file, a sync, or by hand.
	</EmptyState>
{:else}
	<ul class="flex flex-col" data-slot="account-list" aria-label="Accounts">
		{#each accounts as account (account.id)}
			{@const look = resolveAccount(account)}
			{@const closed = account.closed_on !== null}
			<li data-account-id={account.id} data-closed={closed || undefined}>
				<a
					href={`/accounts/${account.id}`}
					class={cn(
						'flex min-h-14 items-center gap-3 border-b border-border px-1 py-2 outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring',
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
	</ul>
{/if}
