<script lang="ts">
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import TreeToggle from '#lib/components/common/tree-toggle.svelte';
	import { foldedRows, toggled } from '#lib/reports/fold.js';
	import type { AccountTrendRow, Column, TrendRow } from '#lib/reports/tables.js';
	import { measureLook } from '#lib/theme/measures.js';
	import { resolveAccount, resolveAccountKind } from '#lib/theme/resolve.js';
	import type { Account } from '#lib/types/domain.js';
	import FigureLink from './figure-link.svelte';

	// *By account* of Over time: the accounts grouped by kind, as Balances has them, with a column per
	// period and a total, each amount a link to the ledger for its row and period; the kind's total
	// beneath. It opens collapsed to the kinds; a kind's row expands to its accounts.
	let {
		columns,
		rows,
		total,
		accounts,
		currency,
		locale = 'en'
	}: {
		columns: readonly Column[];
		rows: readonly AccountTrendRow[];
		total: TrendRow;
		accounts: ReadonlyMap<number, Account>;
		currency: string;
		locale?: string;
	} = $props();

	// opens collapsed to the top level; the state is per row key, so a refetch keeps what is open
	let expanded = $state.raw<ReadonlySet<string>>(new Set());
	const shown = $derived(foldedRows(rows, expanded));
	const totalLook = $derived(measureLook(total.measure));
</script>

<div class="overflow-x-auto">
	<table class="w-full text-sm" data-slot="account-trend-table">
		<caption class="sr-only">Amounts per account and period, in {currency}</caption>
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
			{#each shown as row (row.key)}
				{@const account = row.accountId === null ? undefined : accounts.get(row.accountId)}
				{@const look = account ? resolveAccount(account) : resolveAccountKind(row.accountKind)}
				<tr
					class="border-b border-border/60"
					data-account-kind={row.depth === 0 ? row.accountKind : undefined}
					data-account={row.accountId}
				>
					<th scope="row" class="sticky left-0 bg-card py-2 pr-4 pl-4 text-left font-normal">
						<span
							class="flex items-center gap-2 whitespace-nowrap"
							style:padding-left={`${row.depth * 1.5}rem`}
						>
							<TreeToggle
								name={row.name}
								expanded={row.expanded}
								toggleable={row.hasChildren}
								ontoggle={() => (expanded = toggled(expanded, row.key))}
							/>
							<DimensionIcon icon={look.icon} color={look.color} />
							<span class={row.depth === 0 ? 'font-medium' : ''}>{row.name}</span>
						</span>
					</th>
					{#each row.cells as cell, i (columns[i].key)}
						<td
							class="px-3 py-2 text-right whitespace-nowrap last:pr-4"
							data-column={columns[i].key}
						>
							<FigureLink line={cell.line} href={cell.href} {locale} />
						</td>
					{/each}
				</tr>
			{/each}
		</tbody>
		<tfoot>
			<tr class="font-medium" data-row="total">
				<th scope="row" class="sticky left-0 bg-card py-2 pr-4 pl-4 text-left">
					<span class="flex items-center gap-2">
						<DimensionIcon icon={totalLook.icon} color={totalLook.color} size="compact" />
						{total.label}
					</span>
				</th>
				{#each total.cells as cell, i (columns[i].key)}
					<td class="px-3 py-2 text-right whitespace-nowrap last:pr-4">
						{#if cell.kind === 'line'}
							<FigureLink line={cell.line} href={cell.href} {locale} />
						{/if}
					</td>
				{/each}
			</tr>
		</tfoot>
	</table>
</div>
