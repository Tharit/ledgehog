<script lang="ts">
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import { formatCount, formatRate } from '#lib/format/index.js';
	import { kindHref, type Scope } from '#lib/reports/links.js';
	import { categoryTable } from '#lib/reports/tables.js';
	import type { ByCategory } from '#lib/reports/types.js';
	import { dimensionVars } from '#lib/theme/dimensions.js';
	import { resolveCategory } from '#lib/theme/resolve.js';
	import type { Category } from '#lib/types/domain.js';
	import FigureLink from './figure-link.svelte';

	// The category tree as a table (the data beside the donut): each category's entries, amount,
	// share of the kind and a thin bar; a parent's own entries are a child row "Name (itself)" so a
	// row is the sum of its children. Every amount links to the ledger filtered to the category and
	// the period (its descendants included, unless it is "(itself)").
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

	const rows = $derived(categoryTable(report, categories, scope));
	const kindLabel = $derived(report.kind === 'income' ? 'Income' : 'Expense');
</script>

<table class="w-full text-sm" data-slot="category-table">
	<thead class="text-xs text-muted-foreground">
		<tr class="border-b border-border">
			<th class="py-2 text-left font-medium" scope="col">Category</th>
			<th class="py-2 text-right font-medium" scope="col">Entries</th>
			<th class="py-2 text-right font-medium" scope="col">Amount ({report.base_currency})</th>
			<th class="py-2 text-right font-medium" scope="col">Share</th>
			<th class="w-24 py-2 sm:w-40" scope="col"><span class="sr-only">Share as a bar</span></th>
		</tr>
	</thead>
	<tbody>
		{#each rows as row (row.key)}
			{@const look = resolveCategory(categories.get(row.categoryId), categories)}
			<tr class="border-b border-border/60" data-category={row.categoryId} data-itself={row.itself}>
				<th scope="row" class="py-2 text-left font-normal">
					<span class="flex items-center gap-2" style:padding-left={`${row.depth * 1.5}rem`}>
						{#if row.itself}
							<span class="text-muted-foreground">{row.name}</span>
						{:else}
							<DimensionIcon icon={look.icon} color={look.color} />
							<span class={row.depth === 0 ? 'font-medium' : ''}>{row.name}</span>
						{/if}
					</span>
				</th>
				<td class="py-2 text-right tabular-nums">{formatCount(row.line.count, locale)}</td>
				<td class="py-2 text-right">
					<FigureLink line={row.line} href={row.href} {locale} />
				</td>
				<td class="py-2 text-right text-muted-foreground tabular-nums">
					{formatRate(row.shareBp, locale)}
				</td>
				<td class="py-2 pl-3" aria-hidden="true">
					<span class="block h-1.5 rounded-full bg-muted">
						<span
							class="block h-1.5 rounded-full"
							style:width={`${row.bar * 100}%`}
							style:background-color={dimensionVars(look.color).fg}
						></span>
					</span>
				</td>
			</tr>
		{/each}
	</tbody>
	<tfoot>
		<tr class="font-medium">
			<th scope="row" class="py-2 text-left">{kindLabel}, total</th>
			<td class="py-2 text-right tabular-nums">{formatCount(report.total.count, locale)}</td>
			<td class="py-2 text-right">
				<FigureLink line={report.total} href={kindHref(scope, report.kind, categories)} {locale} />
			</td>
			<td></td>
			<td></td>
		</tr>
	</tfoot>
</table>
