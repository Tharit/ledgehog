<script lang="ts">
	import AbsentValue from '#lib/components/common/absent-value.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import LineFigure from '#lib/components/reports/line-figure.svelte';
	import { formatDate } from '#lib/format/index.js';
	import { UNPAIRED_TRANSFERS_HREF } from '#lib/reports/figures.js';
	import type { NetWorth } from '#lib/reports/types.js';
	import CardRow from './card-row.svelte';
	import FigureCard from './figure-card.svelte';

	// Every account's balance at today's rate (spec §8). The rows say what the figure leaves out or
	// holds back: what could not be valued (per currency, with the accounts), the transfers still
	// unpaired, and the change since the end of last month.
	let { netWorth, locale = 'en' }: { netWorth: NetWorth | null; locale?: string } = $props();

	const accountsText = (count: number) => (count === 1 ? '1 account' : `${count} accounts`);
	const transfersText = (count: number) =>
		count === 1 ? '1 transfer still unpaired' : `${count} transfers still unpaired`;
</script>

<FigureCard title="Net worth" loading={netWorth === null}>
	{#snippet figure()}
		{#if netWorth?.total}
			<MoneyDisplay
				minor={netWorth.total.amount}
				currency={netWorth.total.currency}
				{locale}
				showPlus={false}
				showCurrency
			/>
		{:else}
			<AbsentValue
				label="unvalued"
				explanation="No balance could be valued: no usable exchange rate."
			/>
		{/if}
	{/snippet}
	{#snippet rows()}
		{#if netWorth}
			{#each netWorth.unvalued as unvalued (unvalued.amount.currency)}
				<CardRow label={`Unvalued, ${accountsText(unvalued.accounts)}`}>
					<MoneyDisplay
						minor={unvalued.amount.amount}
						currency={unvalued.amount.currency}
						{locale}
						showPlus={false}
						showCurrency
					/>
				</CardRow>
			{/each}
			{#if netWorth.unpaired_transfers.count > 0}
				<CardRow
					label={transfersText(netWorth.unpaired_transfers.count)}
					href={UNPAIRED_TRANSFERS_HREF}
				>
					<LineFigure line={netWorth.unpaired_transfers} {locale} />
				</CardRow>
			{/if}
			{#if netWorth.since}
				<CardRow label={`Since ${formatDate(netWorth.since.on, locale)}`}>
					<MoneyDisplay
						minor={netWorth.since.change.amount}
						currency={netWorth.since.change.currency}
						{locale}
						showCurrency
					/>
				</CardRow>
			{/if}
		{/if}
	{/snippet}
</FigureCard>
