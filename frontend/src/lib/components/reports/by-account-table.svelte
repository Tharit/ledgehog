<script lang="ts">
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import TreeToggle from '#lib/components/common/tree-toggle.svelte';
	import { formatCount } from '#lib/format/index.js';
	import { foldedRows, toggled } from '#lib/reports/fold.js';
	import type { Scope } from '#lib/reports/links.js';
	import { accountTable } from '#lib/reports/tables.js';
	import type { ByAccount } from '#lib/reports/types.js';
	import type { Account, Category } from '#lib/types/domain.js';
	import FigureLink from './figure-link.svelte';

	// The data beside the sankey: Income and Expense, each category (its *By category* figure) with
	// its accounts beneath it, then the unclassified and the reconciliations with their accounts;
	// and Transfers, each sending account with the receiving accounts beneath. A group that the
	// answer gives no figure for has none: the client adds nothing. Every figure links to the
	// ledger with the equivalent filter. Groups open collapsed, as the category tree does.
	let {
		report,
		categories,
		accounts,
		scope,
		locale = 'en'
	}: {
		report: ByAccount;
		categories: ReadonlyMap<number, Category>;
		accounts: ReadonlyMap<number, Account>;
		scope: Scope;
		locale?: string;
	} = $props();

	// the state is per row key (the section is in it), so a refetch keeps what is open
	let expanded = $state.raw<ReadonlySet<string>>(new Set());
	const sections = $derived(
		accountTable(report, categories, accounts, scope).map((section) => ({
			...section,
			rows: foldedRows(section.rows, expanded)
		}))
	);
</script>

<div class="overflow-x-auto">
	<table class="w-full text-sm" data-slot="account-table">
		<thead class="text-xs text-muted-foreground">
			<tr class="border-b border-border bg-muted">
				<th class="py-2 pl-4 text-left font-medium" scope="col">Name</th>
				<th class="px-3 py-2 text-right font-medium" scope="col">Entries</th>
				<th class="px-3 py-2 pr-4 text-right font-medium" scope="col"
					>Amount ({report.base_currency})</th
				>
			</tr>
		</thead>
		{#each sections.filter((s) => s.rows.length > 0) as section (section.key)}
			<tbody data-section={section.key}>
				<tr>
					<th scope="colgroup" colspan="3" class="px-4 pt-6 pb-1 text-left text-base font-semibold">
						{section.label}
					</th>
				</tr>
				{#each section.rows as row (row.key)}
					<tr class={['border-b border-border/60', row.total && 'font-medium']} data-row={row.key}>
						<th scope="row" class="py-2 pl-4 text-left font-normal">
							<span class="flex items-center gap-2" style:padding-left={`${row.depth * 1.5}rem`}>
								<TreeToggle
									name={row.label}
									expanded={row.expanded}
									toggleable={row.hasChildren}
									ontoggle={() => (expanded = toggled(expanded, row.key))}
								/>
								<DimensionIcon icon={row.icon} color={row.color} size="compact" />
								<span class={row.depth === 0 ? 'font-medium' : ''}>{row.label}</span>
							</span>
						</th>
						<td class="px-3 py-2 text-right tabular-nums">
							{#if row.line}{formatCount(row.line.count, locale)}{/if}
						</td>
						<td class="px-3 py-2 pr-4 text-right">
							{#if row.line}
								<FigureLink line={row.line} href={row.href ?? undefined} {locale} />
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		{/each}
	</table>
</div>
