<script lang="ts">
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import type { PanelGroup } from '#lib/units/groups.js';
	import type { EntryView } from '#lib/units/view.js';

	// The counter-leg a commit creates (spec §5.7, patterns §4.5), read-only: what the entry will
	// be (a transfer of this amount on this date), its purpose and where it comes from ("created
	// for" the leg). Nothing here edits: the amount received, the date and the purpose are the
	// leg's to decide; it becomes an ordinary entry when the commit has made it.
	let {
		view,
		ghost,
		lookups,
		locale = 'en'
	}: {
		view: EntryView;
		ghost: NonNullable<PanelGroup['ghost']>;
		lookups: Lookups;
		locale?: string;
	} = $props();

	const forAccount = $derived(
		ghost.forAccountId !== null ? lookups.accounts.get(ghost.forAccountId) : undefined
	);
</script>

<section
	aria-label="Counter-leg created when you commit"
	class="flex flex-col gap-2 rounded-lg border border-dashed bg-muted/30 p-4 text-[13px] text-muted-foreground"
	data-slot="counter-leg-block"
	data-entry-id={view.id}
>
	<dl class="grid grid-cols-[8rem_1fr] items-baseline gap-x-4 gap-y-1.5">
		<dt>Type</dt>
		<dd data-slot="counter-leg-type">Transfer</dd>
		<dt>Amount</dt>
		<dd data-slot="counter-leg-amount">
			{#if view.amount}
				<MoneyDisplay
					minor={view.amount.amount}
					currency={view.amount.currency}
					{locale}
					showCurrency
					class="inline"
				/>
			{:else}
				<span>To be entered</span>
			{/if}
		</dd>
		<dt>Date</dt>
		<dd data-slot="counter-leg-date">
			<DateDisplay date={view.row?.booked_on ?? ''} {locale} />
		</dd>
		<dt>Purpose</dt>
		<dd data-slot="counter-leg-purpose">
			{#if ghost.purpose}{ghost.purpose}{:else}<span>None</span>{/if}
		</dd>
		<dt>Provenance</dt>
		<dd data-slot="counter-leg-provenance" class="flex flex-wrap items-center gap-x-1">
			<span>created for</span>
			{#if forAccount}
				<AccountDot name={forAccount.name} color={resolveAccount(forAccount).color} />
			{:else}
				<span>its partner</span>
			{/if}
		</dd>
	</dl>
</section>
