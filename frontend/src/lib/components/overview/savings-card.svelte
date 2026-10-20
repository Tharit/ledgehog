<script lang="ts">
	import IncompleteMarker from '#lib/components/reports/incomplete-marker.svelte';
	import LineFigure from '#lib/components/reports/line-figure.svelte';
	import { formatMonth, formatRate } from '#lib/format/index.js';
	import type { Overview, SavingsSpan } from '#lib/reports/types.js';
	import CardRow from './card-row.svelte';
	import FigureCard from './figure-card.svelte';

	// Savings over income of the last 12 complete months, in whole percent, "—" when income is not
	// positive (spec §8). A marker says when the period holds unclassified entries, reconciliations
	// or unvalued amounts. Rows: last month, this month so far and what was kept of the income.
	let { savings, locale = 'en' }: { savings: Overview['savings'] | null; locale?: string } =
		$props();
</script>

{#snippet rate(span: SavingsSpan)}
	<span class="inline-flex items-center gap-1.5">
		{formatRate(span.rate_bp, locale)}
		{#if span.incomplete}<IncompleteMarker />{/if}
	</span>
{/snippet}

<FigureCard
	title="Savings rate"
	caption={savings
		? `Last 12 months, ${formatMonth(savings.last_12.from, locale)} – ${formatMonth(savings.last_12.to, locale)}`
		: undefined}
	loading={savings === null}
>
	{#snippet figure()}
		{#if savings}{@render rate(savings.last_12)}{/if}
	{/snippet}
	{#snippet rows()}
		{#if savings}
			<CardRow label="Last month">{@render rate(savings.last_month)}</CardRow>
			<CardRow label="This month so far">{@render rate(savings.this_month)}</CardRow>
			{#if savings.last_12.income.count > 0}
				<CardRow label="Kept">
					<span class="inline-flex flex-wrap items-baseline justify-end gap-x-1.5">
						<LineFigure line={savings.last_12.savings} {locale} showPlus={false} />
						of
						<LineFigure line={savings.last_12.income} {locale} showPlus={false} />
						income
					</span>
				</CardRow>
			{/if}
		{/if}
	{/snippet}
</FigureCard>
