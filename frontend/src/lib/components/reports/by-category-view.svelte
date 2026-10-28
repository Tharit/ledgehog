<script lang="ts">
	import { donutSlices } from '#lib/reports/charts.js';
	import { categoryHref, type Scope } from '#lib/reports/links.js';
	import { notInCategories } from '#lib/reports/tables.js';
	import type { ByCategory } from '#lib/reports/types.js';
	import type { Category } from '#lib/types/domain.js';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import Card from '#lib/components/common/card.svelte';
	import CategoryDonut from './category-donut.svelte';
	import CategoryTable from './category-table.svelte';
	import FigureLink from './figure-link.svelte';

	// *By category* (reports.md): the largest six categories and "Other" as a donut with its legend
	// (colour and name; the amounts are in the tooltips and the table), the category tree as a
	// table with what is not in the categories above as a section of it. The table is the readable data of
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
			<Card
				class="flex flex-wrap items-center justify-center gap-x-10 gap-y-6"
				data-slot="donut-section"
			>
				<div class="w-64 max-w-full">
					<CategoryDonut slices={donut.slices} currency={report.base_currency} {locale} {sign} />
				</div>
				<ul class="flex flex-col gap-1 text-sm" data-slot="donut-legend">
					{#each donut.slices as slice (slice.key)}
						<li class="flex items-center gap-2" data-slice={slice.key}>
							<DimensionIcon icon={slice.icon} color={slice.color} size="compact" />
							<span>{slice.label}</span>
						</li>
					{/each}
				</ul>
			</Card>
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

		<Card variant="flush">
			<CategoryTable {report} {categories} {scope} {locale} />
		</Card>
	</div>
{/if}
