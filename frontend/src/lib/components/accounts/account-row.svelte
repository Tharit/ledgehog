<script lang="ts">
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import { ACCOUNT_KINDS } from '#lib/accounts/kinds.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import type { Account } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';
	import AccountFacts from './account-facts.svelte';

	// One account's row (ux/views/account.md): its icon and name, its kind, its balance with the
	// currency code and its facts line. The row opens the account page. A closed account is muted.
	// `inset` is a row beneath a group row, indented to sit under its name.
	let {
		account,
		locale = 'en',
		today,
		flush = false,
		inset = false
	}: {
		account: Account;
		locale?: string;
		today: string;
		/** edge to edge in a flush card, else padded for a card of the Overview */
		flush?: boolean;
		inset?: boolean;
	} = $props();

	const kindLabel = (kind: string) => ACCOUNT_KINDS.find((k) => k.kind === kind)?.label ?? kind;
	const look = $derived(resolveAccount(account));
	const closed = $derived(account.closed_on !== null);
</script>

<a
	href={`/accounts/${account.id}`}
	class={cn(
		'flex min-h-14 items-center gap-3 border-b border-border py-2 outline-none hover:bg-row-hover focus-visible:ring-2 focus-visible:ring-ring',
		flush ? (inset ? 'pr-4 pl-10' : 'px-4') : 'px-1',
		closed && 'text-muted-foreground'
	)}
	data-account-id={account.id}
	data-closed={closed || undefined}
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
