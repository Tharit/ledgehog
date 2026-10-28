<script lang="ts">
	import LineFigure from '#lib/components/reports/line-figure.svelte';
	import { formatDate, formatMonthName } from '#lib/format/index.js';
	import { byCategoryHref, ledgerHref } from '#lib/reports/figures.js';
	import type { Overview } from '#lib/reports/types.js';
	import { iconFor } from '#lib/theme/icons.js';
	import { MEASURE_ICONS } from '#lib/theme/measures.js';
	import CardRow from '#lib/components/common/card-row.svelte';
	import FigureCard from '#lib/components/common/figure-card.svelte';

	// This month so far: expense-kind flows, refunds netting, signed (spec §8). Its first two
	// rows are the unclassified amount out and the month's reconciliations, so that the figure does
	// not understate itself. The rows then compare with last month, in full and to the same day. Every
	// amount links to the report or the ledger that lists what it sums.
	let { spend, locale = 'en' }: { spend: Overview['spend'] | null; locale?: string } = $props();

	const month = $derived(spend?.this_month);
	const beside = $derived(
		month
			? [
					{
						line: month.unclassified_out,
						label: 'Plus unclassified',
						href: ledgerHref({
							from: month.from,
							to: month.to,
							uncategorised: true,
							direction: 'out'
						})
					},
					{
						line: month.reconciliations,
						label: 'Plus reconciliations',
						href: ledgerHref({ from: month.from, to: month.to, type: ['reconciliation'] })
					}
				].filter((part) => part.line.count > 0)
			: []
	);
</script>

<FigureCard
	title="Spend"
	icon={iconFor(MEASURE_ICONS.expense)}
	caption={month ? `${formatMonthName(month.from, locale)} so far` : undefined}
	loading={spend === null}
>
	{#snippet figure()}
		{#if month}
			<a
				href={byCategoryHref(month.from, month.to)}
				class="rounded-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
			>
				<LineFigure line={month.spend} {locale} showPlus={false} />
			</a>
		{/if}
	{/snippet}
	{#snippet rows()}
		{#if spend && month}
			{#each beside as part (part.label)}
				<CardRow label={part.label} href={part.href}>
					<LineFigure line={part.line} {locale} />
				</CardRow>
			{/each}
			<CardRow label="Last month" href={byCategoryHref(spend.last_month.from, spend.last_month.to)}>
				<LineFigure line={spend.last_month.spend} {locale} showPlus={false} />
			</CardRow>
			<CardRow
				label={`Last month to ${formatDate(spend.last_month_to_date.to, locale)}`}
				href={byCategoryHref(spend.last_month_to_date.from, spend.last_month_to_date.to)}
			>
				<LineFigure line={spend.last_month_to_date.spend} {locale} showPlus={false} />
			</CardRow>
		{/if}
	{/snippet}
</FigureCard>
