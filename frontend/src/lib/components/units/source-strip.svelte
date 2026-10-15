<script lang="ts">
	import { buttonVariants } from '#lib/components/ui/button/index.js';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import type { SourceGroup } from '#lib/units/describe.js';
	import type { SourceTransaction } from '#lib/types/domain.js';

	// What the source said (patterns §4.5, read-only): the normalised columns of the source
	// transaction, one strip per source of the unit. An entry entered by hand has a source of its
	// own and shows it the same way, with a small "Entered by hand"; one with none says only that.
	let { groups, locale = 'en' }: { groups: readonly SourceGroup[]; locale?: string } = $props();

	function fields(source: SourceTransaction): [string, string][] {
		const rows: [string, string | null][] = [
			['Counterparty', source.counterparty_name],
			['Counterparty reference', source.counterparty_ref],
			['Purpose', source.purpose],
			['Booking text', source.booking_text]
		];
		return rows.filter((row): row is [string, string] => row[1] !== null && row[1] !== '');
	}
</script>

{#each groups as group, i (i)}
	<section
		aria-label={group.source ? 'Source transaction' : 'Entered by hand'}
		class="rounded-lg bg-muted px-4 py-3 text-[13px]"
		data-slot="source-strip"
	>
		{#if !group.source}
			<p class="text-muted-foreground">Entered by hand</p>
		{:else}
			<div class="mb-1 flex flex-wrap items-baseline gap-x-3">
				<h3 class="text-xs font-medium text-muted-foreground">Source transaction</h3>
				{#if group.authored}
					<span class="text-xs text-muted-foreground" data-slot="authored-hint"
						>Entered by hand</span
					>
				{/if}
			</div>
			<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5">
				<dt class="text-muted-foreground">Amount</dt>
				<dd>
					<MoneyDisplay
						minor={group.source.amount.amount}
						currency={group.source.amount.currency}
						{locale}
						showCurrency
						class="inline"
					/>
				</dd>
				{#each fields(group.source) as [label, value] (label)}
					<dt class="text-muted-foreground">{label}</dt>
					<dd class="min-w-0 break-words">{value}</dd>
				{/each}
				{#if group.source.instructed_amount}
					<dt class="text-muted-foreground">Instructed amount</dt>
					<dd>
						<MoneyDisplay
							minor={group.source.instructed_amount.amount}
							currency={group.source.instructed_amount.currency}
							{locale}
							showCurrency
							class="inline"
						/>
					</dd>
				{/if}
			</dl>
			<!-- another page, not a decision: no ellipsis. A new tab, because the panel may hold a draft -->
			<a
				href={`/settings/rules/new?from=${group.entryIds[0]}`}
				target="_blank"
				rel="noopener"
				class={[buttonVariants({ variant: 'outline' }), 'mt-3']}
				data-slot="add-rule-from-source">Add rule from this transaction</a
			>
		{/if}
	</section>
{/each}
