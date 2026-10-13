<script lang="ts">
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import type { SourceGroup } from '#lib/units/describe.js';

	// What the source said (patterns §4.5, read-only): the normalised columns of the source
	// transaction, one strip per source of the unit; "Entered by hand" for an authored entry.
	let { groups, locale = 'en' }: { groups: readonly SourceGroup[]; locale?: string } = $props();

	function fields(group: Extract<SourceGroup, { kind: 'source' }>): [string, string][] {
		const s = group.source;
		const rows: [string, string | null][] = [
			['Counterparty', s.counterparty_name],
			['Counterparty reference', s.counterparty_ref],
			['Purpose', s.purpose],
			['Booking text', s.booking_text]
		];
		return rows.filter((row): row is [string, string] => row[1] !== null && row[1] !== '');
	}
</script>

{#each groups as group, i (i)}
	<section
		aria-label={group.kind === 'source' ? 'Source transaction' : 'Entered by hand'}
		class="rounded-lg bg-muted px-4 py-3 text-[13px]"
		data-slot="source-strip"
	>
		{#if group.kind === 'authored'}
			<p class="text-muted-foreground">Entered by hand</p>
		{:else}
			<h3 class="mb-1 text-xs font-medium text-muted-foreground">Source transaction</h3>
			<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5">
				{#each fields(group) as [label, value] (label)}
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
		{/if}
	</section>
{/each}
