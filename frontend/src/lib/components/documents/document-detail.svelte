<script lang="ts">
	import CardRow from '#lib/components/common/card-row.svelte';
	import Card from '#lib/components/common/card.svelte';
	import FigureCard from '#lib/components/common/figure-card.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import { formatDate } from '#lib/format/index.js';
	import type { Account, DocumentDetail } from '#lib/types/domain.js';
	import { documentTitle, notBookedReason } from './describe.js';
	import DocumentLines from './document-lines.svelte';

	// One document (view sketch: ux/views/documents.md): its merchant, total and lines, read-only. The
	// total is a figure card with the reference and the booking as its rows; the booked entries and
	// the lines are lists in cards under their headings.
	let {
		document,
		locale = 'en',
		accounts = new Map(),
		onopenentry
	}: {
		document: DocumentDetail;
		locale?: string;
		/** the accounts by id: the booking's account is named */
		accounts?: ReadonlyMap<number, Account>;
		/** an entry of the booking was chosen: its unit opens in the review panel */
		onopenentry?: (entryId: number) => void;
	} = $props();

	const booking = $derived(document.booking);
	const bookedOn = $derived(
		booking ? (accounts.get(booking.account_id)?.name ?? `Account ${booking.account_id}`) : null
	);
	const reason = $derived(
		document.not_booked
			? notBookedReason(document.not_booked, {
					provider: document.provider,
					accountName:
						document.not_booked.account_id === null
							? null
							: (accounts.get(document.not_booked.account_id)?.name ?? null),
					locale
				})
			: null
	);
</script>

<div class="flex flex-col gap-6">
	<PageHeader
		level={1}
		title={documentTitle(document)}
		description={`${document.provider} · ${formatDate(document.occurred_on, locale)}`}
	/>

	<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" data-slot="figure-cards">
		<FigureCard title="Total">
			{#snippet figure()}
				<MoneyDisplay
					minor={document.total.amount}
					currency={document.total.currency}
					{locale}
					showCurrency
				/>
			{/snippet}
			{#snippet rows()}
				<CardRow label="Reference">
					<span class="break-all">{document.external_id}</span>
				</CardRow>
				{#if booking}
					<CardRow label="Booked on">
						<span data-slot="booked-on">
							<a href={`/accounts/${booking.account_id}`} class="underline underline-offset-2">
								{bookedOn}
							</a>
						</span>
					</CardRow>
				{:else if reason}
					<p class="text-muted-foreground" data-slot="not-booked">Not booked: {reason}</p>
				{/if}
			{/snippet}
		</FigureCard>
	</div>

	{#if booking && booking.entries.length > 0}
		<section aria-labelledby="document-booking" class="flex max-w-2xl flex-col gap-1">
			<h2 id="document-booking" class="text-base font-semibold">Booked entries</h2>
			<Card variant="flush" element="ul" data-slot="booking-entries">
				{#each booking.entries as entry (entry.id)}
					<li
						class="flex items-center gap-3 border-b border-border px-4 py-1.5 text-sm last:border-b-0"
					>
						<button
							type="button"
							class="min-w-0 flex-1 truncate rounded-sm text-left outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
							title="Open in review"
							onclick={() => onopenentry?.(entry.id)}
						>
							{entry.source_text ?? `Entry ${entry.id}`}
						</button>
						<MoneyDisplay
							minor={entry.amount.amount}
							currency={entry.amount.currency}
							{locale}
							class="shrink-0"
						/>
					</li>
				{/each}
			</Card>
		</section>
	{/if}

	<section aria-labelledby="document-lines" class="flex flex-col gap-1">
		<h2 id="document-lines" class="text-base font-semibold">Lines</h2>
		{#if document.lines.length === 0}
			<p class="text-sm text-muted-foreground">This document has no lines.</p>
		{:else}
			<DocumentLines lines={document.lines} {locale} />
		{/if}
	</section>
</div>
