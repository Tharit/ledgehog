<script lang="ts">
	import CheckIcon from '@lucide/svelte/icons/check';
	import AbsentValue from '#lib/components/common/absent-value.svelte';
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import ReviewBadge from '#lib/components/common/review-badge.svelte';
	import { formatDate } from '#lib/format/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import type { DocumentDetail } from '#lib/types/domain.js';
	import CarrierLink from './carrier-link.svelte';
	import { documentTitle } from './describe.js';

	// One document (view sketch: ux/views/documents.md): its merchant, total and lines. A linked
	// document names the transaction carrying it; one carried by no entry lists the transactions it
	// would match, confirmed ones included, each marked with its unit's state. Choosing one opens
	// the review panel on it with this document picked; the link is written only by that commit.
	let {
		document,
		lookups,
		locale = 'en',
		onopencarrier,
		onpickmatch
	}: {
		document: DocumentDetail;
		lookups: Lookups;
		locale?: string;
		/** the carrying transaction: open it in the review panel */
		onopencarrier: (entryId: number, origin: HTMLElement) => void;
		/** a match: open the review panel on it with this document picked in the draft */
		onpickmatch: (entryId: number, documentId: number, origin: HTMLElement) => void;
	} = $props();

	const showMatchCurrency = $derived(
		new Set(document.matches.map((m) => m.amount.currency)).size > 1
	);
</script>

<div class="flex flex-col gap-6">
	<PageHeader
		level={1}
		title={documentTitle(document)}
		description={`${document.provider} · ${formatDate(document.occurred_on, locale)}`}
	/>

	<dl class="grid max-w-2xl grid-cols-[8rem_1fr] gap-x-4 gap-y-2 text-sm">
		<dt class="text-muted-foreground">Total</dt>
		<dd>
			<MoneyDisplay
				minor={document.total.amount}
				currency={document.total.currency}
				{locale}
				showCurrency
				class="inline"
			/>
		</dd>
		<dt class="text-muted-foreground">Reference</dt>
		<dd class="truncate">{document.external_id}</dd>
		<dt class="text-muted-foreground">Carried by</dt>
		<dd class="min-w-0">
			{#if document.carrier}
				<CarrierLink carrier={document.carrier} {lookups} {locale} onopen={onopencarrier} />
			{:else}
				<AbsentValue label="Not linked" explanation="No transaction carries this document yet" />
			{/if}
		</dd>
	</dl>

	<section aria-labelledby="document-lines" class="flex flex-col gap-2">
		<h2 id="document-lines" class="text-base font-semibold">Lines</h2>
		{#if document.lines.length === 0}
			<p class="text-sm text-muted-foreground">This document has no lines.</p>
		{:else}
			<div class="overflow-x-auto">
				<table class="w-full min-w-md text-[13px]">
					<thead>
						<tr
							class="h-8 border-b border-border bg-muted text-xs font-medium text-muted-foreground"
						>
							<th scope="col" class="px-3 text-left font-medium">Description</th>
							<th scope="col" class="w-20 px-3 text-right font-medium">Qty</th>
							<th scope="col" class="w-32 px-3 text-right font-medium">Amount</th>
						</tr>
					</thead>
					<tbody>
						{#each document.lines as line (line.line_no)}
							<tr class="h-8 border-b border-border">
								<td class="px-3">{line.description}</td>
								<td class="px-3 text-right tabular-nums">{line.qty ?? ''}</td>
								<td class="px-3">
									<MoneyDisplay
										minor={line.amount.amount}
										currency={line.amount.currency}
										{locale}
									/>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>

	{#if document.carrier === null}
		<section aria-labelledby="document-matches" class="flex flex-col gap-2">
			<h2 id="document-matches" class="text-base font-semibold">Transactions it would match</h2>
			{#if document.matches.length === 0}
				<EmptyState title="No transaction would match this document">
					A transaction matches when its payee names this provider and its amount and date fit the
					document. It may not have been imported yet.
				</EmptyState>
			{:else}
				<ul class="flex flex-col" aria-label="Matching transactions">
					{#each document.matches as match (match.entry_id)}
						{@const account = lookups.accounts.get(match.account_id)}
						{@const payee =
							match.payee_id === null ? undefined : lookups.payees.get(match.payee_id)}
						<li
							class="flex min-h-9 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border py-1 text-[13px]"
						>
							<span class="w-24 shrink-0"><DateDisplay date={match.booked_on} {locale} /></span>
							<span class="w-36 min-w-0 shrink-0">
								{#if account}
									<AccountDot name={account.name} color={resolveAccount(account).color} />
								{:else}
									Account {match.account_id}
								{/if}
							</span>
							<span class="min-w-0 flex-1 truncate">
								{payee?.name ?? match.display_text ?? ''}
							</span>
							<span class="flex w-32 shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
								{#if match.confirmed}
									<CheckIcon size={14} strokeWidth={1.75} aria-hidden="true" />Confirmed
								{:else}
									<ReviewBadge flag="unconfirmed" />Unconfirmed
								{/if}
							</span>
							<span class="w-32 shrink-0">
								<MoneyDisplay
									minor={match.amount.amount}
									currency={match.amount.currency}
									{locale}
									showCurrency={showMatchCurrency}
								/>
							</span>
							{#if match.instructed_amount}
								<span class="w-32 shrink-0 text-xs text-muted-foreground">
									<MoneyDisplay
										minor={match.instructed_amount.amount}
										currency={match.instructed_amount.currency}
										{locale}
										showCurrency
										class="inline"
									/>
								</span>
							{/if}
							{#if match.document_id !== null}
								<span class="text-xs text-muted-foreground">carries another document</span>
							{/if}
							<Button
								variant="link"
								class="h-auto p-0"
								onclick={(event) => onpickmatch(match.entry_id, document.id, event.currentTarget)}
							>
								Open to review
							</Button>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	{/if}
</div>
