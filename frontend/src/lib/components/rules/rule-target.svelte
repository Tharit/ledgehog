<script lang="ts">
	import AbsentValue from '#lib/components/common/absent-value.svelte';
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import type { RuleSets } from '#lib/rules/types.js';
	import { kindWord } from '#lib/rules/targets.js';
	import {
		categoryPath,
		resolveAccount,
		resolveCategory,
		resolvePayee
	} from '#lib/theme/resolve.js';

	// What a rule sets, drawn the way the ledger draws it: a category with its icon, a payee with
	// its icon or initial, a counter-account as "→" and its dot (design §6). An id the lists do not
	// know is shown as absent, never guessed at. `full` writes a category's whole path.
	let {
		sets,
		id,
		lookups,
		full = false
	}: { sets: RuleSets; id: number | null; lookups: Lookups; full?: boolean } = $props();

	const category = $derived(
		sets === 'category' && id !== null ? lookups.categories.get(id) : undefined
	);
	const payee = $derived(sets === 'payee' && id !== null ? lookups.payees.get(id) : undefined);
	const account = $derived(
		sets === 'counter_account' && id !== null ? lookups.accounts.get(id) : undefined
	);
	const categoryLook = $derived(resolveCategory(category, lookups.categories));
	const payeeLook = $derived(payee ? resolvePayee(payee) : undefined);
</script>

<span class="inline-flex min-w-0 items-center gap-2" data-slot="rule-target">
	{#if category}
		<DimensionIcon icon={categoryLook.icon} color={categoryLook.color} />
		<span class="truncate">{full ? categoryPath(category, lookups.categories) : category.name}</span
		>
	{:else if payee && payeeLook}
		<DimensionIcon
			icon={payeeLook.icon}
			color={payeeLook.color}
			initial={payeeLook.icon ? undefined : payeeLook.initial}
		/>
		<span class="truncate">{payee.name}</span>
	{:else if account}
		<span aria-hidden="true">&rarr;</span>
		<AccountDot name={account.name} color={resolveAccount(account).color} />
	{:else}
		<AbsentValue
			label={id === null ? `No ${kindWord(sets)}` : `Unknown ${kindWord(sets)}`}
			explanation={id === null
				? 'Nothing chosen yet'
				: 'This is not in the loaded list; it may have been merged or deleted'}
		/>
	{/if}
</span>
