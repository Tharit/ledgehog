<script lang="ts">
	import FunnelPlusIcon from '@lucide/svelte/icons/funnel-plus';
	import { bookedFromText, bookingDocumentHref } from '#lib/accounts/booking.js';
	import IconButton from '#lib/components/common/icon-button.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import type { SourceGroup } from '#lib/units/describe.js';
	import type { SourceTransaction } from '#lib/types/domain.js';

	// What the source said (patterns §4.5, read-only): the normalised columns of the source
	// transaction, one strip per source of the unit. An entry entered by hand has a source of its
	// own and shows it the same way, with a small "Entered by hand"; one with none says only that.
	// The "Create rule from this transaction" icon sits in the top-right corner, revealed by hover or
	// focus on the strip (opacity only, patterns §11.3) and always visible where there is no hover.
	// A booking (spec §5.8) says where it came from instead: "Booked from amazon order 304-1",
	// opening the document, or "Booked from Amazon clearing’s charge".
	let {
		groups,
		locale = 'en',
		accountName = () => undefined
	}: {
		groups: readonly SourceGroup[];
		locale?: string;
		/** an account's name, for "Booked from <account>’s charge" */
		accountName?: (id: number) => string | undefined;
	} = $props();

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
		class="group relative rounded-lg bg-muted px-4 py-3 text-[13px]"
		data-slot="source-strip"
	>
		{#if !group.source}
			<p class="text-muted-foreground">Entered by hand</p>
		{:else}
			<div class="mb-1 flex flex-wrap items-baseline gap-x-3">
				{#if group.source.booking}
					{@const booking = group.source.booking}
					{@const href = bookingDocumentHref(booking)}
					{@const text = bookedFromText(
						booking,
						booking.account_id === null ? null : (accountName(booking.account_id) ?? null)
					)}
					<h3 class="text-xs font-medium text-muted-foreground" data-slot="booked-from">
						{#if href}
							<!-- a new tab, because the panel may hold a draft -->
							<a
								{href}
								target="_blank"
								rel="noopener"
								class="underline underline-offset-2 hover:text-foreground">{text}</a
							>
						{:else}
							{text}
						{/if}
					</h3>
				{:else}
					<h3 class="text-xs font-medium text-muted-foreground">Source transaction</h3>
				{/if}
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
			<!-- Funnel-plus: the rules icon, plus create. Another page, not a decision: no ellipsis. A new tab, because the panel may hold a draft -->
			<div
				class="absolute top-1.5 right-1.5 text-muted-foreground opacity-0 group-focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
				data-slot="add-rule-reveal"
			>
				<IconButton
					compact
					verb="Create rule from this transaction"
					label="Create rule from this transaction"
					href={`/settings/rules/new?from=${group.entryIds[0]}`}
					target="_blank"
					rel="noopener"
					data-slot="add-rule-from-source"
				>
					<FunnelPlusIcon aria-hidden="true" />
				</IconButton>
			</div>
		{/if}
	</section>
{/each}
