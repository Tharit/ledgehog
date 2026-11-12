<script lang="ts">
	import { gridTemplate, type Column } from '#lib/accounts/columns.js';
	import { describeFacts, describePerformance } from '#lib/accounts/facts.js';
	import { ACCOUNT_KINDS } from '#lib/accounts/kinds.js';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import type { Account } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';

	// One account's row of a group's card (ux/views/account.md), a cell per column: its icon and name
	// (with its kind beneath where kinds mix), its data age, its notices, for a depot or asset its gain
	// and return, and its balance. The name is the link and its hit area is the whole row.
	let {
		account,
		columns,
		currency,
		locale = 'en',
		today,
		showKind = false
	}: {
		account: Account;
		columns: readonly Column[];
		/** the currency the group shares, which its header names; null: each balance carries its code */
		currency: string | null;
		locale?: string;
		today: string;
		/** the kind beneath the name, in the Closed group where kinds mix */
		showKind?: boolean;
	} = $props();

	const kindLabel = (kind: string) => ACCOUNT_KINDS.find((k) => k.kind === kind)?.label ?? kind;
	const look = $derived(resolveAccount(account));
	const facts = $derived(describeFacts(account, { locale, today }));
	const age = $derived(facts[0]);
	const notices = $derived(facts.slice(1));
	const performance = $derived(describePerformance(account, { locale }));
</script>

<div
	role="row"
	class="relative grid min-h-12 items-center gap-x-3 border-b border-border px-3 text-sm focus-within:ring-2 focus-within:ring-ring focus-within:ring-inset hover:bg-row-hover"
	style:grid-template-columns={gridTemplate(columns)}
	data-account-id={account.id}
>
	{#each columns as column (column.id)}
		{#if column.id === 'account'}
			<div role="cell" class="flex min-w-0 items-center gap-3 py-2">
				<DimensionIcon icon={look.icon} color={look.color} size="comfortable" />
				<span class="flex min-w-0 flex-col">
					<a
						href={`/accounts/${account.id}`}
						class="truncate font-medium outline-none after:absolute after:inset-0"
					>
						{account.name}
					</a>
					{#if showKind}
						<span class="truncate text-xs text-muted-foreground">{kindLabel(account.kind)}</span>
					{/if}
				</span>
			</div>
		{:else if column.id === 'age'}
			<div
				role="cell"
				class="min-w-0 truncate text-muted-foreground"
				title={age.title ?? age.text}
				data-fact="age"
			>
				{age.text}
			</div>
		{:else if column.id === 'notices'}
			<div
				role="cell"
				class="flex min-w-0 flex-wrap gap-x-3 text-xs text-muted-foreground"
				data-slot="notices"
			>
				{#each notices as fact (fact.id)}
					<span class="truncate" data-fact={fact.id} title={fact.title}>{fact.text}</span>
				{/each}
			</div>
		{:else if column.id === 'gain'}
			<div role="cell" class="min-w-0 truncate text-right" data-slot="gain">
				{#if performance}
					<MoneyDisplay
						minor={performance.gainMoney.amount}
						currency={performance.gainMoney.currency}
						{locale}
						showCurrency={currency === null}
					/>
				{/if}
			</div>
		{:else if column.id === 'return'}
			<div
				role="cell"
				class={cn(
					'min-w-0 truncate text-right',
					!performance?.hasReturn && 'text-muted-foreground'
				)}
				data-slot="return"
			>
				{performance?.return ?? '—'}
			</div>
		{:else}
			<div role="cell" class="min-w-0 truncate text-right font-medium" data-slot="balance">
				<MoneyDisplay
					minor={account.balance.amount}
					currency={account.balance.currency}
					{locale}
					showCurrency={currency === null}
					showPlus={false}
				/>
			</div>
		{/if}
	{/each}
</div>
