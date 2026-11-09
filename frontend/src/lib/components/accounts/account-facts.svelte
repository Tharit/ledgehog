<script lang="ts">
	import { describeFacts, describePerformance } from '#lib/accounts/facts.js';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import type { Account } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';

	// An account's balance with its currency code and the facts line under it (patterns §4.4,
	// spec §3.11): data age, "balance not anchored", the unexplained difference. Quiet notices,
	// never prompts. Shared by the accounts list and the account page.
	let {
		account,
		locale = 'en',
		today,
		align = 'left',
		class: className
	}: {
		account: Account;
		locale?: string;
		/** the household's day, for the data age */
		today: string;
		align?: 'left' | 'right';
		class?: string;
	} = $props();

	const facts = $derived(describeFacts(account, { locale, today }));
	const performance = $derived(describePerformance(account, { locale }));
</script>

<div
	class={cn('flex flex-col gap-0.5', align === 'right' ? 'items-end text-right' : '', className)}
	data-slot="account-facts"
>
	<MoneyDisplay
		minor={account.balance.amount}
		currency={account.balance.currency}
		{locale}
		showCurrency
		showPlus={false}
		class="text-base font-semibold"
	/>
	{#if performance}
		<p class="text-xs text-muted-foreground" data-slot="performance-line">
			{performance.hasReturn
				? `gain ${performance.gain} · ${performance.return}`
				: `gain ${performance.gain}`}
		</p>
	{/if}
	<p
		class={cn(
			'flex flex-wrap gap-x-2 text-xs text-muted-foreground',
			align === 'right' && 'justify-end'
		)}
		data-slot="facts-line"
	>
		{#each facts as fact, i (fact.id)}
			{#if i > 0}<span aria-hidden="true">·</span>{/if}
			<span data-fact={fact.id} title={fact.title}>{fact.text}</span>
		{/each}
	</p>
</div>
