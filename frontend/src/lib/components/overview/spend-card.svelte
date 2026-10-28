<script lang="ts">
	import LineFigure from '#lib/components/reports/line-figure.svelte';
	import { formatDate, formatMonthName } from '#lib/format/index.js';
	import { byCategoryHref, ledgerHref } from '#lib/reports/figures.js';
	import type { Overview } from '#lib/reports/types.js';
	import CardRow from '#lib/components/common/card-row.svelte';
	import FigureCard from '#lib/components/common/figure-card.svelte';

	// This month so far: expense-kind flows, refunds netting, signed (spec §8). Directly under it
	// the unclassified amount out and the month's reconciliations, so that the figure does not
	// understate itself. The rows compare with last month, in full and to the same day. Every
	// amount links to the report or the ledger that lists what it sums.
	let { spend, locale = 'en' }: { spend: Overview['spend'] | null; locale?: string } = $props();

	const month = $derived(spend?.this_month);
	const beside = $derived(
		month
			? [
					{
						line: month.unclassified_out,
						label: 'unclassified',
						href: ledgerHref({
							from: month.from,
							to: month.to,
							uncategorised: true,
							direction: 'out'
						})
					},
					{
						line: month.reconciliations,
						label: 'reconciliations',
						href: ledgerHref({ from: month.from, to: month.to, type: ['reconciliation'] })
					}
				].filter((part) => part.line.count > 0)
			: []
	);
</script>

<FigureCard
	title="Spend"
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
			{#if beside.length > 0}
				<p class="flex flex-wrap items-baseline gap-x-1.5 text-sm" data-slot="spend-beside">
					<span class="text-muted-foreground">plus</span>
					{#each beside as part, i (part.label)}
						{#if i > 0}<span class="text-muted-foreground">&middot;</span>{/if}
						<a href={part.href} class="inline-flex items-baseline gap-1.5 hover:underline">
							<LineFigure line={part.line} {locale} />
							<span class="text-muted-foreground">{part.label}</span>
						</a>
					{/each}
				</p>
			{/if}
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
