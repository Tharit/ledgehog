<script lang="ts">
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import * as Command from '#lib/components/ui/command/index.js';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import { formatDate, formatMoney } from '#lib/format/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import type { UnitDraftFlow } from '#lib/units/unit-draft-flow.svelte.js';
	import {
		legWords,
		offerGroups,
		offerHints,
		proposalEvidence,
		shownOffers,
		shownPartner,
		stateSentence
	} from '#lib/units/transfer.js';
	import type { UnitOffer } from '#lib/units/types.js';
	import type { EntryView } from '#lib/units/view.js';
	import { cn } from '#lib/utils.js';
	import EvidenceLine from './evidence-line.svelte';

	// The partner of a transfer leg (spec §5.7, patterns §4.3, §11): who it is paired with (or the
	// partner the server proposes, italic), or why it has none in plain words; and the control that
	// picks another: a popover listing the offers in the server's order, "Open" then "Paired
	// elsewhere". Each offer says in one line what picking it will do; the real consequences show
	// in the preview after the pick. The list scrolls; ↑ ↓ move, Enter picks, Esc closes.
	let {
		view,
		flow,
		lookups,
		locale = 'en',
		counterAccountId,
		onaddaccount
	}: {
		view: EntryView;
		flow: UnitDraftFlow;
		lookups: Lookups;
		locale?: string;
		/** the leg's counter-account as the draft leaves it */
		counterAccountId: number | null;
		/** "Add account" for the currency a transfer needs; the trigger takes the focus back */
		onaddaccount: (trigger: HTMLElement | null, currency: string) => void;
	} = $props();

	// only called for a leg the preview told about
	const transfer = $derived(view.transfer!);
	const words = $derived({ lookups, locale });
	const partner = $derived(shownPartner(transfer));
	const sentence = $derived(stateSentence(transfer, counterAccountId, words));
	const groups = $derived(offerGroups(transfer.offers));
	const total = $derived(shownOffers(transfer.offers).length);
	const paired = $derived(partner !== null && !partner.proposal);
	const loading = $derived(flow.previewStatus === 'loading' || flow.stale);

	let open = $state(false);
	let query = $state('');
	$effect(() => {
		if (!open) query = '';
	});

	function searchText(offer: UnitOffer): string {
		return [
			lookups.accounts.get(offer.account_id)?.name,
			offer.description,
			formatDate(offer.booked_on, locale),
			offer.amount ? formatMoney(offer.amount.amount, offer.amount.currency, { locale }) : ''
		]
			.join(' ')
			.toLowerCase();
	}

	const needle = $derived(query.trim().toLowerCase());
	const filtered = $derived(
		groups
			.map((g) => ({
				...g,
				offers: needle === '' ? g.offers : g.offers.filter((o) => searchText(o).includes(needle))
			}))
			.filter((g) => g.offers.length > 0)
	);

	function choose(offer: UnitOffer) {
		if (offer.entry_id === null) return;
		open = false;
		flow.pickPartner(view.id, offer.entry_id);
	}
</script>

<dt class="pt-1.5 text-muted-foreground">Partner</dt>
<dd class="flex min-w-0 flex-col gap-1" data-slot="partner" data-state={transfer.state}>
	{#if partner}
		{@const account = lookups.accounts.get(partner.account_id)}
		<p
			class={cn(
				'flex flex-wrap items-center gap-x-2',
				partner.proposal && 'text-muted-foreground italic'
			)}
			data-slot="partner-leg"
			data-proposal={partner.proposal || undefined}
		>
			{#if !partner.proposal}<span>Paired with</span>{/if}
			{#if account}
				<AccountDot name={account.name} color={resolveAccount(account).color} />
			{:else}
				<span>Account {partner.account_id}</span>
			{/if}
			<span aria-hidden="true">·</span>
			<DateDisplay date={partner.booked_on} {locale} />
			{#if partner.amount}
				<span aria-hidden="true">·</span>
				<MoneyDisplay
					minor={partner.amount.amount}
					currency={partner.amount.currency}
					{locale}
					showCurrency
					showPlus={false}
					class="inline"
				/>
			{/if}
		</p>
		{#if partner.description}
			<p class="truncate text-xs text-muted-foreground">{partner.description}</p>
		{/if}
		{#if partner.proposal}
			<span class="block text-xs text-muted-foreground italic" data-slot="evidence" data-proposal>
				{proposalEvidence(partner)}
			</span>
		{:else}
			<EvidenceLine
				evidence={view.picked ? { text: 'picked by you', proposal: false } : view.pairEvidence}
			/>
		{/if}
	{:else}
		<p data-slot="partner-none">No partner yet</p>
		{#if sentence}
			<p class="text-xs text-muted-foreground" data-slot="partner-state">{sentence}</p>
		{/if}
	{/if}

	<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
		{#if transfer.state === 'needs_account' && transfer.needs_account}
			{@const currency = transfer.needs_account.currency}
			<ActionButton
				variant="link"
				class="h-auto p-0 text-xs"
				data-slot="partner-add-account"
				onclick={(event) => onaddaccount(event.currentTarget, currency)}
			>
				Add account
			</ActionButton>
		{:else}
			<Popover.Root bind:open>
				<Popover.Trigger>
					{#snippet child({ props })}
						<ActionButton
							variant="outline"
							data-picker="partner"
							disabled={flow.committing}
							{...props}
						>
							{paired ? 'Pick another partner…' : 'Choose partner…'}
						</ActionButton>
					{/snippet}
				</Popover.Trigger>
				<Popover.Content
					align="start"
					class="w-[26rem] max-w-[90vw] gap-0 p-1"
					aria-label="Choose a partner"
				>
					<Command.Root shouldFilter={false} aria-busy={loading}>
						{#if total > 0}
							<Command.Input
								placeholder="Find a candidate…"
								aria-label="Search candidates"
								bind:value={query}
							/>
						{/if}
						<Command.List aria-label="Partner candidates" class="max-h-72">
							{#each filtered as group (group.key)}
								<Command.Group heading={group.label} data-group={group.key}>
									{#each group.offers as offer (offer.entry_id)}
										{@const account = lookups.accounts.get(offer.account_id)}
										{@const hints = offerHints(offer, transfer, words)}
										<Command.Item
											value={`offer-${offer.entry_id}`}
											class="items-start"
											data-offer={offer.entry_id}
											data-kind={offer.kind}
											onSelect={() => choose(offer)}
										>
											<span class="flex min-w-0 flex-1 flex-col gap-0.5">
												<span class="flex flex-wrap items-center gap-x-2">
													{#if account}
														<AccountDot name={account.name} color={resolveAccount(account).color} />
													{:else}
														<span>Account {offer.account_id}</span>
													{/if}
													<DateDisplay date={offer.booked_on} {locale} />
													{#if offer.amount}
														<MoneyDisplay
															minor={offer.amount.amount}
															currency={offer.amount.currency}
															{locale}
															showCurrency
															class="inline"
														/>
													{/if}
													{#if offer.exact}
														<span class="rounded-sm bg-muted px-1 text-xs" data-tag="exact"
															>exact</span
														>
													{/if}
													{#if offer.proposed}
														<span
															class="rounded-sm bg-muted px-1 text-xs italic"
															data-tag="proposed">proposed</span
														>
													{/if}
													{#if offer.kind === 'untyped_entry'}
														<span class="text-xs text-muted-foreground" data-tag="untyped"
															>not yet typed</span
														>
													{/if}
												</span>
												{#if offer.description}
													<span class="truncate text-xs text-muted-foreground"
														>{offer.description}</span
													>
												{/if}
												{#if offer.paired_with}
													<span class="text-xs text-muted-foreground" data-slot="offer-paired">
														paired with {legWords(offer.paired_with, words)}
													</span>
												{/if}
												{#if hints.length > 0}
													<span class="text-xs text-muted-foreground" data-slot="offer-hint">
														{hints.join(' · ')}
													</span>
												{/if}
											</span>
										</Command.Item>
									{/each}
								</Command.Group>
							{/each}
							{#if total === 0}
								<p
									class="px-2 py-6 text-center text-sm text-muted-foreground"
									data-slot="offers-empty"
								>
									No candidates in this window
								</p>
							{:else if filtered.length === 0}
								<p class="px-2 py-6 text-center text-sm text-muted-foreground">No match.</p>
							{/if}
						</Command.List>
					</Command.Root>
					{#if transfer.has_more && flow.nextWindow !== null}
						<div class="border-t px-1 pt-1">
							<ActionButton
								variant="link"
								class="h-auto justify-start p-1 text-xs"
								data-slot="load-more"
								disabled={loading}
								onclick={() => flow.widenWindow()}
							>
								Load more candidates
							</ActionButton>
						</div>
					{:else if flow.previewWindow !== null}
						<p
							class="border-t px-2 pt-1 pb-0.5 text-xs text-muted-foreground"
							data-slot="window-note"
						>
							Candidates within {flow.previewWindow} days.
						</p>
					{/if}
				</Popover.Content>
			</Popover.Root>
			{#if view.picked}
				<ActionButton
					variant="link"
					class="h-auto p-0 text-xs"
					onclick={() => flow.clearPairing(view.id)}
				>
					Reset to proposal
				</ActionButton>
			{/if}
		{/if}
	</div>
</dd>
