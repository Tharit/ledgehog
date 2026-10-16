<script lang="ts">
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import { formatDate, formatMoney } from '#lib/format/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import type { DocumentCarrier } from '#lib/types/domain.js';

	// The transaction carrying a document, as one compact line ("Giro · Oct 9, 2026 · −47.31"):
	// a button that opens it in the review panel (the origin is handed back to focus afterwards).
	let {
		carrier,
		lookups,
		locale = 'en',
		onopen
	}: {
		carrier: DocumentCarrier;
		lookups: Lookups;
		locale?: string;
		onopen: (entryId: number, origin: HTMLElement) => void;
	} = $props();

	const account = $derived(lookups.accounts.get(carrier.account_id));
	const amount = $derived(
		formatMoney(carrier.amount.amount, carrier.amount.currency, {
			locale,
			showCurrency: true,
			showPlus: true
		})
	);
</script>

<button
	type="button"
	class="flex max-w-full min-w-0 items-center gap-1.5 rounded-sm text-left text-[13px] outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
	title="Open this transaction"
	onclick={(event) => onopen(carrier.entry_id, event.currentTarget)}
>
	{#if account}
		<AccountDot name={account.name} color={resolveAccount(account).color} />
	{:else}
		<span class="truncate">Account {carrier.account_id}</span>
	{/if}
	<span class="shrink-0 text-muted-foreground">
		· {formatDate(carrier.booked_on, locale)} · <span class="amount">{amount}</span>
	</span>
</button>
