<script lang="ts">
	import AbsentValue from '#lib/components/common/absent-value.svelte';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import TreeToggle from '#lib/components/common/tree-toggle.svelte';
	import { formatCount, formatRate } from '#lib/format/index.js';
	import { foldedRows, toggled } from '#lib/reports/fold.js';
	import { kindHref, type Scope } from '#lib/reports/links.js';
	import { categoryTable, notInCategories } from '#lib/reports/tables.js';
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

	// opens collapsed to the top level; the state is per row key, so a refetch keeps what is open
	let expanded = $state.raw<ReadonlySet<string>>(new Set());
	const rows = $derived(foldedRows(categoryTable(report, categories, scope), expanded));
	const side = $derived(notInCategories(report, scope));
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
						<TreeToggle
							name={row.name}
							expanded={row.expanded}
							toggleable={row.hasChildren}
							ontoggle={() => (expanded = toggled(expanded, row.key))}
						/>
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
	<tbody data-slot="category-total">
		<tr class="font-medium">
			<th scope="row" class="py-2 text-left">{kindLabel}, total</th>
			<td class="py-2 text-right tabular-nums">{formatCount(report.total.count, locale)}</td>
			<td class="py-2 text-right">
				<FigureLink line={report.total} href={kindHref(scope, report.kind, categories)} {locale} />
			</td>
			<td></td>
			<td></td>
		</tr>
	</tbody>
	<!-- what stands beside the tree: the same columns, a labelled section, not a group to fold -->
	<tbody data-slot="not-in-categories">
		<tr>
			<th scope="colgroup" colspan="5" class="pt-6 pb-1 text-left text-base font-semibold">
				Not in the categories above
			</th>
		</tr>
		{#each side.lines as item (item.key)}
			<tr class="border-b border-border/60" data-line={item.key}>
				<th scope="row" class="py-2 text-left font-normal">
					<AbsentValue label={item.label} explanation={item.explanation} />
				</th>
				<td class="py-2 text-right tabular-nums">{formatCount(item.line.count, locale)}</td>
				<td class="py-2 text-right">
					<FigureLink line={item.line} href={item.href} {locale} />
				</td>
				<td></td>
				<td></td>
			</tr>
		{/each}
		<tr class="border-b border-border/60" data-line="unconfirmed">
			<th scope="row" class="py-2 text-left font-normal">
				<AbsentValue
					label="Not yet confirmed"
					explanation="Entries of this period whose values are proposals. The table includes their proposed categories."
				/>
			</th>
			<td class="py-2 text-right tabular-nums">
				{#if side.unconfirmed.count > 0}
					<a
						href={side.unconfirmed.href}
						aria-label={`${formatCount(side.unconfirmed.count, locale)} ${side.unconfirmed.count === 1 ? 'entry' : 'entries'} not yet confirmed`}
						class="rounded-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
						>{formatCount(side.unconfirmed.count, locale)}</a
					>
				{:else}
					<span class="text-muted-foreground">0</span>
				{/if}
			</td>
			<td></td>
			<td></td>
			<td></td>
		</tr>
	</tbody>
</table>
