<script lang="ts">
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import type { CategoryTrendRow, Column, TrendRow } from '#lib/reports/tables.js';
	import { resolveCategory } from '#lib/theme/resolve.js';
	import type { Category } from '#lib/types/domain.js';
	import FigureLink from './figure-link.svelte';

	// *By category* of Over time: the category tree with a column per period and a total, each amount
	// a link to the ledger for its category and period; the kind's total beneath.
	let {
		columns,
		rows,
		total,
		categories,
		currency,
		locale = 'en'
	}: {
		columns: readonly Column[];
		rows: readonly CategoryTrendRow[];
		total: TrendRow;
		categories: ReadonlyMap<number, Category>;
		currency: string;
		locale?: string;
	} = $props();
</script>

<div class="overflow-x-auto">
	<table class="w-full text-sm" data-slot="category-trend-table">
		<caption class="sr-only">Amounts per category and period, in {currency}</caption>
		<thead class="text-xs text-muted-foreground">
			<tr class="border-b border-border">
				<th class="sticky left-0 bg-background py-2 pr-4 text-left font-medium" scope="col"
					>{currency}</th
				>
				{#each columns as column (column.key)}
					<th class="px-3 py-2 text-right font-medium whitespace-nowrap" scope="col"
						>{column.label}</th
					>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each rows as row (row.key)}
				{@const look = resolveCategory(categories.get(row.categoryId), categories)}
				<tr
					class="border-b border-border/60"
					data-category={row.categoryId}
					data-itself={row.itself}
				>
					<th scope="row" class="sticky left-0 bg-background py-2 pr-4 text-left font-normal">
						<span
							class="flex items-center gap-2 whitespace-nowrap"
							style:padding-left={`${row.depth * 1.5}rem`}
						>
							{#if row.itself}
								<span class="text-muted-foreground">{row.name}</span>
							{:else}
								<DimensionIcon icon={look.icon} color={look.color} />
								<span class={row.depth === 0 ? 'font-medium' : ''}>{row.name}</span>
							{/if}
						</span>
					</th>
					{#each row.cells as cell, i (columns[i].key)}
						<td class="px-3 py-2 text-right whitespace-nowrap" data-column={columns[i].key}>
							<FigureLink line={cell.line} href={cell.href} {locale} />
						</td>
					{/each}
				</tr>
			{/each}
		</tbody>
		<tfoot>
			<tr class="font-medium" data-row="total">
				<th scope="row" class="sticky left-0 bg-background py-2 pr-4 text-left">{total.label}</th>
				{#each total.cells as cell, i (columns[i].key)}
					<td class="px-3 py-2 text-right whitespace-nowrap">
						{#if cell.kind === 'line'}
							<FigureLink line={cell.line} href={cell.href} {locale} />
						{/if}
					</td>
				{/each}
			</tr>
		</tfoot>
	</table>
</div>
