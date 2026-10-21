<script lang="ts">
	import AbsentValue from '#lib/components/common/absent-value.svelte';
	import { formatCount } from '#lib/format/index.js';
	import { donutSlices } from '#lib/reports/charts.js';
	import { categoryHref, type Scope } from '#lib/reports/links.js';
	import { notInCategories } from '#lib/reports/tables.js';
	import type { ByCategory } from '#lib/reports/types.js';
	import { dimensionVars } from '#lib/theme/dimensions.js';
	import type { Category } from '#lib/types/domain.js';
	import CategoryDonut from './category-donut.svelte';
	import CategoryTable from './category-table.svelte';
	import FigureLink from './figure-link.svelte';

	// *By category* (reports.md): the largest six categories and "Other" as a donut with its legend
	// (colour and name; the amounts are in the tooltips and the table), the category tree as a
	// table, and beneath it what is not in the categories above. The table is the readable data of
	// the chart.
	let {
		report,
		categories,
		scope,
		locale = 'en'
	}: {
		report: ByCategory;
		categories: ReadonlyMap<number, Category>;
		scope: Scope;
		locale?: string;
	} = $props();

	const donut = $derived(donutSlices(report, categories));
	const side = $derived(notInCategories(report, scope));
	const sign = $derived(report.kind === 'income' ? 1 : -1);
	const nothing = $derived(
		report.categories.length === 0 &&
			side.lines.every((l) => l.line.count === 0) &&
			side.unconfirmed.count === 0
	);
</script>

{#if nothing}
	<p class="text-sm text-muted-foreground" data-slot="nothing">
		Nothing in this period{scope.accountIds.length + scope.tagIds.length > 0
			? ' with these filters'
			: ''}.
	</p>
{:else}
	<div class="flex flex-col gap-8">
		{#if donut.slices.length > 0}
			<div
				class="flex flex-wrap items-center justify-center gap-x-10 gap-y-6"
				data-slot="donut-section"
			>
				<div class="w-64 max-w-full">
					<CategoryDonut slices={donut.slices} currency={report.base_currency} {locale} {sign} />
				</div>
				<ul class="flex flex-col gap-1 text-sm" data-slot="donut-legend">
					{#each donut.slices as slice (slice.key)}
						<li class="flex items-center gap-2" data-slice={slice.key}>
							<span
								class="size-2.5 shrink-0 rounded-[2px]"
								style:background-color={dimensionVars(slice.color).fg}
								aria-hidden="true"
							></span>
							<span>{slice.label}</span>
						</li>
					{/each}
				</ul>
			</div>
		{/if}
		{#if donut.opposite.length > 0}
			<p class="text-sm text-muted-foreground" data-slot="opposite-note">
				Not in the chart, since their net is of the other sign:
				{#each donut.opposite as item, i (item.categoryId)}
					{i > 0 ? ', ' : ''}{item.name}
					(<FigureLink
						line={item.line}
						href={categoryHref(scope, item.categoryId)}
						{locale}
					/>){/each}.
			</p>
		{/if}

		<CategoryTable {report} {categories} {scope} {locale} />

		<section class="flex flex-col gap-2" aria-labelledby="not-in-categories">
			<h2 id="not-in-categories" class="text-base font-semibold">Not in the categories above</h2>
			<ul class="flex flex-col divide-y divide-border/60 text-sm" data-slot="not-in-categories">
				{#each side.lines as item (item.key)}
					<li class="flex items-baseline justify-between gap-3 py-2" data-line={item.key}>
						<AbsentValue label={item.label} explanation={item.explanation} />
						<span class="flex items-baseline gap-4">
							<span class="text-muted-foreground tabular-nums"
								>{formatCount(item.line.count, locale)}</span
							>
							<FigureLink line={item.line} href={item.href} {locale} />
						</span>
					</li>
				{/each}
				<li class="flex items-baseline justify-between gap-3 py-2" data-line="unconfirmed">
					<AbsentValue
						label="Not yet confirmed"
						explanation="Entries of this period whose values are proposals. The table includes their proposed categories."
					/>
					{#if side.unconfirmed.count > 0}
						<a
							href={side.unconfirmed.href}
							class="rounded-sm tabular-nums outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
						>
							{formatCount(side.unconfirmed.count, locale)}
							{side.unconfirmed.count === 1 ? 'entry' : 'entries'}
						</a>
					{:else}
						<span class="text-muted-foreground tabular-nums">0 entries</span>
					{/if}
				</li>
			</ul>
		</section>
	</div>
{/if}
