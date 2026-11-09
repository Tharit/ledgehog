<script lang="ts">
	import {
		describeFacts,
		describePerformance,
		NET_DEPOSITS_HELP,
		NO_RETURN_HELP
	} from '#lib/accounts/facts.js';
	import { uploadHref, type SourceLine } from '#lib/accounts/sources.js';
	import { formatDate } from '#lib/format/index.js';
	import { otherLoginText } from '#lib/importers/list.js';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import CardRow from '#lib/components/common/card-row.svelte';
	import Card from '#lib/components/common/card.svelte';
	import FigureCard from '#lib/components/common/figure-card.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import type { Account } from '#lib/types/domain.js';

	// What stands under the account page's header (ux/views/account.md), as cards like the
	// Overview's: the "Balance" figure card with the facts line as its rows (data age, "balance not
	// anchored", the unexplained difference), and the "Sources" card (each linked importer instance
	// with its action, or how an unlinked account is fed). A fetch importer's line has "Fetch",
	// where a file importer's has "Upload file". The account's actions are the page header's.
	let {
		account,
		sources,
		sourcesStatus = 'ready',
		locale = 'en',
		today,
		onfetch
	}: {
		account: Account;
		sources: readonly SourceLine[];
		/** the instances are still being read, or could not be */
		sourcesStatus?: 'loading' | 'ready' | 'error';
		locale?: string;
		today: string;
		/** "Fetch" on the line of a fetch importer: a one-item sync of this account (ux/views/sync.md) */
		onfetch?: (instanceId: number) => void;
	} = $props();

	const facts = $derived(describeFacts(account, { locale, today }));
	const performance = $derived(describePerformance(account, { locale }));
	// the cards' subtitle slot keeps its line (a no-break space) where there is no date, so the two
	// figures stay level
	const NO_DATE = '\u00a0';
	const balanceCaption = $derived(
		account.balance_as_of === null ? NO_DATE : `as of ${formatDate(account.balance_as_of, locale)}`
	);
</script>

<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" data-slot="account-summary">
	<FigureCard title="Balance" caption={balanceCaption}>
		{#snippet figure()}
			<MoneyDisplay
				minor={account.balance.amount}
				currency={account.balance.currency}
				{locale}
				showCurrency
				showPlus={false}
			/>
		{/snippet}
		{#snippet rows()}
			{#each facts as fact (fact.id)}
				<span class="text-muted-foreground" data-fact={fact.id} title={fact.title}>{fact.text}</span
				>
			{/each}
		{/snippet}
	</FigureCard>

	{#if performance}
		<FigureCard
			title="Performance"
			caption={performance.asOf ? `as of ${performance.asOf}` : NO_DATE}
		>
			{#snippet figure()}
				<span data-slot="gain">
					<MoneyDisplay
						minor={performance.gainMoney.amount}
						currency={performance.gainMoney.currency}
						{locale}
						showCurrency
					/>
				</span>
			{/snippet}
			{#snippet rows()}
				<div data-slot="net-deposits" class="contents">
					<CardRow label="Net deposits" title={NET_DEPOSITS_HELP}>
						<MoneyDisplay
							minor={performance.netDepositsMoney.amount}
							currency={performance.netDepositsMoney.currency}
							{locale}
							showCurrency
							showPlus={false}
						/>
					</CardRow>
				</div>
				<div data-slot="return" class="contents">
					<CardRow label="Return p.a." title={performance.hasReturn ? undefined : NO_RETURN_HELP}>
						{performance.return}
					</CardRow>
				</div>
			{/snippet}
		</FigureCard>
	{/if}

	<Card
		element="section"
		class={`flex min-w-0 flex-col gap-3 ${performance ? 'xl:col-span-2' : 'xl:col-span-3'}`}
		aria-label="Sources"
	>
		<h2 class="text-sm font-semibold">Sources</h2>
		<div class="flex flex-col gap-1 text-sm" data-slot="sources">
			{#if account.kind === 'clearance'}
				<p class="text-muted-foreground" data-slot="clearance-sources">
					Fed by the orders of its providers{#if account.providers.length === 0}
						(none yet; add them in Edit){:else}:
						{#each account.providers as provider, i (provider)}{#if i > 0},
							{/if}<a
								href={`/documents?provider=${encodeURIComponent(provider)}`}
								class="text-foreground underline underline-offset-2">{provider}</a
							>{/each}{/if}, and by the charges decided as transfers to it.
				</p>
			{:else if sourcesStatus === 'loading'}
				<p class="text-muted-foreground">Looking up the importers…</p>
			{:else if sourcesStatus === 'error'}
				<p class="text-muted-foreground">The importers could not be loaded.</p>
			{:else if sources.length === 0}
				<p class="text-muted-foreground" data-slot="unlinked">
					Entered by hand. To feed it from a file or a sync, link it to an importer in
					<a href="/settings/importers" class="text-foreground underline underline-offset-2"
						>Settings → Importers</a
					>.
				</p>
			{:else}
				<ul class="flex flex-col gap-1">
					{#each sources as source (source.instanceId)}
						<li
							class="flex flex-wrap items-center gap-x-3 gap-y-1"
							data-source-instance={source.instanceId}
						>
							<span class="font-medium">{source.label}</span>
							<span class="text-muted-foreground">
								{source.importer}{source.disabled ? ' · disabled' : ''}
							</span>
							{#if source.otherLogin}
								<span class="text-muted-foreground" data-slot="other-login">
									{otherLoginText(source.otherLogin.name)}
								</span>
							{:else if source.kind === 'file'}
								<ActionButton
									variant="outline"
									href={uploadHref(account.id, source.instanceId)}
									disabled={source.disabled}
								>
									Upload file
								</ActionButton>
							{:else}
								<ActionButton
									variant="outline"
									disabled={source.disabled}
									onclick={() => onfetch?.(source.instanceId)}
								>
									Fetch
								</ActionButton>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	</Card>
</div>
