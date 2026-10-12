<script lang="ts">
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import ReviewBadge from '#lib/components/common/review-badge.svelte';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { ledgerLink } from '#lib/rules/links.js';
	import type { RulePreviewRow, RuleSets } from '#lib/rules/types.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import RuleTarget from './rule-target.svelte';

	// One entry of the preview, compact (32px, one line, design §5): date, account, text, what the
	// list says about it, amount, and a link to the ledger. Everything shown is what the server sent.
	//  match:     an unconfirmed badge, and the earlier rule that takes precedence, if any
	//  different: what the entry holds now for what the rule sets
	//  lost:      the same, and the fields still carrying the rule's key
	let {
		row,
		kind,
		sets,
		lookups,
		ruleName,
		locale = 'en'
	}: {
		row: RulePreviewRow;
		kind: 'match' | 'different' | 'lost';
		sets: RuleSets;
		lookups: Lookups;
		ruleName: (id: number) => string | undefined;
		locale?: string;
	} = $props();

	const account = $derived(lookups.accounts.get(row.account_id));
	const text = $derived(row.description ?? row.counterparty_name);
	const shadow = $derived(
		row.shadowed_by_rule_id === null
			? null
			: (ruleName(row.shadowed_by_rule_id) ?? `#${row.shadowed_by_rule_id}`)
	);
</script>

<li
	class="grid h-8 grid-cols-[6.5rem_8rem_minmax(0,1fr)_auto_6.5rem_1.5rem] items-center gap-x-3 border-b border-border px-2 text-[13px]"
	data-entry-id={row.entry_id}
>
	<DateDisplay date={row.booked_on} {locale} />
	<span class="min-w-0">
		{#if account}<AccountDot name={account.name} color={resolveAccount(account).color} />{/if}
	</span>
	<span class="min-w-0 truncate" title={text ?? undefined}>
		{#if text}{text}{:else}<span class="text-muted-foreground">No text</span>{/if}
	</span>
	<span class="flex min-w-0 items-center gap-2 text-xs">
		{#if kind === 'match'}
			{#if !row.confirmed}<ReviewBadge flag="unconfirmed" />{/if}
			{#if shadow}
				<span class="text-muted-foreground italic">Rule “{shadow}” takes precedence</span>
			{/if}
		{:else}
			<span class="flex items-center gap-1 text-muted-foreground">
				holds <RuleTarget {sets} id={row.current_value} {lookups} />
			</span>
			{#if kind === 'lost' && row.keyed_fields.length > 0}
				<span class="text-muted-foreground">key on {row.keyed_fields.join(', ')}</span>
			{/if}
		{/if}
	</span>
	<MoneyDisplay minor={row.amount.amount} currency={row.amount.currency} {locale} />
	<a
		href={ledgerLink(row)}
		target="_blank"
		rel="noopener"
		class="inline-flex text-muted-foreground hover:text-foreground"
		aria-label="Show in the ledger"
		title="Show in the ledger (that day, that account), in a new tab"
	>
		<ExternalLinkIcon size={14} strokeWidth={1.75} aria-hidden="true" />
	</a>
</li>
