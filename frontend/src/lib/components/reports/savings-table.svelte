<script lang="ts">
	import { formatRate } from '#lib/format/index.js';
	import type { Column, TrendRow } from '#lib/reports/tables.js';
	import FigureLink from './figure-link.svelte';
	import IncompleteMarker from './incomplete-marker.svelte';

	// The rows of *Income and expense* against the periods and a Total column: each column visibly
	// sums to its savings. Income, expense, unclassified and reconciliations link to the ledger;
	// the savings and the rate are derived, so they are not links: their tooltip names what they
	// are made of.
	let {
		columns,
		rows,
		currency,
		locale = 'en'
	}: {
		columns: readonly Column[];
		rows: readonly TrendRow[];
		currency: string;
		locale?: string;
	} = $props();
</script>

<div class="overflow-x-auto">
	<table class="w-full text-sm" data-slot="savings-table">
		<caption class="sr-only">Income, expense and savings per period, in {currency}</caption>
		<thead class="text-xs text-muted-foreground">
			<tr class="border-b border-border bg-muted">
				<th class="sticky left-0 bg-muted py-2 pr-4 pl-4 text-left font-medium" scope="col"
					>{currency}</th
				>
				{#each columns as column (column.key)}
					<th class="px-3 py-2 text-right font-medium whitespace-nowrap last:pr-4" scope="col"
						>{column.label}</th
					>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each rows as row (row.key)}
				<tr
					class={['border-b border-border/60 last:border-b-0', row.strong && 'font-medium']}
					data-row={row.key}
				>
					<th scope="row" class="sticky left-0 bg-card py-2 pr-4 pl-4 text-left font-normal">
						{row.label}
					</th>
					{#each row.cells as cell, i (columns[i].key)}
						<td
							class="px-3 py-2 text-right whitespace-nowrap last:pr-4"
							data-column={columns[i].key}
						>
							{#if cell.kind === 'line'}
								<FigureLink line={cell.line} href={cell.href} title={cell.title} {locale} />
							{:else}
								<span class="inline-flex items-center gap-1" title={cell.title}>
									{#if cell.incomplete}<IncompleteMarker />{/if}
									<span class="tabular-nums">{formatRate(cell.bp, locale)}</span>
								</span>
							{/if}
						</td>
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
</div>
