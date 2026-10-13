<script lang="ts">
	import type { Snippet } from 'svelte';
	import AbsentValue from '#lib/components/common/absent-value.svelte';
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import ReviewBadge from '#lib/components/common/review-badge.svelte';
	import TagChip from '#lib/components/common/tag-chip.svelte';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { ENTRY_TYPE_INFO } from '#lib/ledger/types.js';
	import { resolveAccount, resolveTag } from '#lib/theme/resolve.js';
	import type { Entry } from '#lib/types/domain.js';
	import { describeKey, keyOf, type Evidence, type RuleNames } from '#lib/units/evidence.js';
	import { cn } from '#lib/utils.js';
	import EvidenceLine from './evidence-line.svelte';

	// One entry of a unit, read-only: its amount, date and account, then each value with the basis
	// it was derived on (patterns §4.3). Proposals are italic. Editing arrives with the draft.
	let {
		entry,
		lookups,
		rules,
		locale = 'en'
	}: { entry: Entry; lookups: Lookups; rules: RuleNames; locale?: string } = $props();

	const account = $derived(lookups.accounts.get(entry.account_id));
	const counterAccount = $derived(
		entry.counter_account_id === null ? undefined : lookups.accounts.get(entry.counter_account_id)
	);
	const partnerAccount = $derived(
		entry.partner ? lookups.accounts.get(entry.partner.account_id) : undefined
	);
	const payee = $derived(entry.payee_id === null ? undefined : lookups.payees.get(entry.payee_id));
	const category = $derived(
		entry.category_id === null ? undefined : lookups.categories.get(entry.category_id)
	);
	const tags = $derived(
		entry.tag_ids.flatMap((id) => {
			const tag = lookups.tags.get(id);
			return tag ? [tag] : [];
		})
	);
	const typeName = $derived(entry.type ? (ENTRY_TYPE_INFO[entry.type]?.name ?? entry.type) : null);

	function evidence(field: string): Evidence | null {
		return describeKey(keyOf(entry.derivation, field), rules, locale);
	}
	const typeEvidence = $derived(evidence('type'));
	const payeeEvidence = $derived(evidence('payee'));
	const categoryEvidence = $derived(evidence('category'));
	// a pair's counter-account is the pair's own: its key is `counterpart` when the pair filled it
	const counterEvidence = $derived(evidence('counter_account') ?? evidence('counterpart'));
</script>

{#snippet row(label: string, evidence: Evidence | null, value: Snippet)}
	<dt class="text-muted-foreground">{label}</dt>
	<dd class="min-w-0">
		<span class={cn(evidence?.proposal && 'text-muted-foreground italic')}>{@render value()}</span>
		<EvidenceLine {evidence} />
	</dd>
{/snippet}

<section
	aria-label={`Entry ${entry.id}`}
	class="flex flex-col gap-3 rounded-lg border bg-card p-4 text-[13px]"
	data-slot="entry-block"
	data-entry-id={entry.id}
>
	<div class="flex flex-wrap items-center gap-x-4 gap-y-1">
		<MoneyDisplay
			minor={entry.amount.amount}
			currency={entry.amount.currency}
			{locale}
			showCurrency
			class="text-lg font-semibold"
		/>
		<DateDisplay date={entry.booked_on} {locale} />
		{#if account}
			<AccountDot name={account.name} color={resolveAccount(account).color} />
		{/if}
		<span class="flex items-center gap-1">
			{#each entry.review_flags as flag (flag)}<ReviewBadge {flag} />{/each}
		</span>
	</div>

	<dl class="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-2">
		{#snippet typeValue()}{typeName ?? ''}{/snippet}
		{@render row('Type', typeEvidence, typeValue)}

		{#if entry.type === 'transfer'}
			{#snippet counterValue()}
				{#if counterAccount}
					<AccountDot name={counterAccount.name} color={resolveAccount(counterAccount).color} />
				{:else}
					<AbsentValue label="→ ?" explanation="This transfer needs a counter account" />
				{/if}
			{/snippet}
			{@render row('Counter account', counterEvidence, counterValue)}
		{:else}
			{#snippet payeeValue()}
				{#if payee}{payee.name}{:else}<AbsentValue
						label="No payee"
						explanation="No payee has been set"
					/>{/if}
			{/snippet}
			{@render row('Payee', payeeEvidence, payeeValue)}
			{#snippet categoryValue()}
				{#if category}{category.name}{:else}<AbsentValue
						label="Unclassified"
						explanation="No category yet; entries are classified in review"
					/>{/if}
			{/snippet}
			{@render row('Category', categoryEvidence, categoryValue)}
		{/if}

		<dt class="text-muted-foreground">Description</dt>
		<dd class="min-w-0 break-words">
			{#if entry.description}{entry.description}{:else}<AbsentValue
					label="None"
					explanation="This entry has no description of its own"
				/>{/if}
		</dd>
		{#if entry.note}
			<dt class="text-muted-foreground">Note</dt>
			<dd class="min-w-0 break-words">{entry.note}</dd>
		{/if}

		{#if entry.type === 'transfer' && entry.partner}
			<dt class="text-muted-foreground">Partner leg</dt>
			<dd class="flex flex-wrap items-center gap-x-3" data-slot="partner">
				{#if partnerAccount}
					<AccountDot name={partnerAccount.name} color={resolveAccount(partnerAccount).color} />
				{/if}
				<DateDisplay date={entry.partner.booked_on} {locale} />
				<MoneyDisplay
					minor={entry.partner.amount.amount}
					currency={entry.partner.amount.currency}
					{locale}
					showCurrency
					class="inline"
				/>
			</dd>
		{/if}

		<dt class="text-muted-foreground">Tags</dt>
		<dd class="flex flex-wrap items-center gap-1">
			{#each tags as tag (tag.id)}
				<TagChip name={tag.name} color={resolveTag(tag).color} />
			{:else}
				<AbsentValue label="None" explanation="Tags are added from the ledger with t" />
			{/each}
		</dd>
	</dl>
</section>
