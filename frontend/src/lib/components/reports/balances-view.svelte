<script lang="ts">
	import AbsentValue from '#lib/components/common/absent-value.svelte';
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import { balanceRows, pointColumnLabel } from '#lib/reports/charts.js';
	import type { Balances } from '#lib/reports/shapes.js';
	import { balanceTable, type BalanceCell } from '#lib/reports/tables.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import type { Account } from '#lib/types/domain.js';
	import BalanceChart from './balance-chart.svelte';

	// *Balances* (reports.md): the balance at each month-end, the net worth by default and the
	// accounts the user toggles on, grouped by kind. The table has every line against the
	// month-ends; an account with no valued balance is listed beneath it and not charted.
	let {
		report,
		accounts,
		locale = 'en'
	}: {
		report: Balances;
		accounts: ReadonlyMap<number, Account>;
		locale?: string;
	} = $props();

	let shown = $state<number[]>([]);
	let showNet = $state(true);

	const table = $derived(balanceTable(report, accounts, locale));
	const chart = $derived(balanceRows(report, accounts, new Set(shown), locale, showNet));
	const columns = $derived(
		report.points.map((p) => ({ key: p, label: pointColumnLabel(p, locale) }))
	);

	function toggle(id: number, on: boolean) {
		shown = on ? [...shown, id] : shown.filter((x) => x !== id);
	}
</script>

{#snippet figure(cell: BalanceCell)}
	{#if cell.minor === null && cell.note}
		<AbsentValue label="unvalued" explanation={cell.note} />
	{:else if cell.minor === null}
		<!-- no balance yet is not an absent value (design §7), just nothing to show -->
		<span class="text-muted-foreground" aria-hidden="true">—</span>
		<span class="sr-only">no balance yet</span>
	{:else}
		<span title={cell.note}>
			<MoneyDisplay minor={cell.minor} currency={cell.currency} {locale} showPlus={false} />
		</span>
	{/if}
{/snippet}

<div class="flex flex-col gap-6">
	{#if report.points.length === 0}
		<p class="text-sm text-muted-foreground" data-slot="nothing">No month-end in this period.</p>
	{:else}
		{#if chart.lines.length === 0}
			<p
				class="flex h-72 items-center justify-center text-sm text-muted-foreground"
				data-slot="nothing-selected"
			>
				Nothing selected.
			</p>
		{:else}
			<BalanceChart
				lines={chart.lines}
				rows={chart.rows}
				currency={report.base_currency}
				{locale}
			/>
		{/if}

		<fieldset class="flex flex-col gap-2" data-slot="account-toggles">
			<legend class="mb-1 text-sm font-medium">Show in the chart</legend>
			<div class="flex flex-wrap items-center gap-x-4 gap-y-1">
				<span class="w-20 text-xs text-muted-foreground">Total</span>
				<label class="flex items-center gap-2 text-sm">
					<input type="checkbox" class="size-4 accent-primary" bind:checked={showNet} />
					<span class="inline-flex items-center gap-1.5">
						<span class="size-2 shrink-0 rounded-full bg-primary" aria-hidden="true"></span>
						Net worth
					</span>
				</label>
			</div>
			{#if table.groups.length > 0}
				{#each table.groups as group (group.key)}
					<div class="flex flex-wrap items-center gap-x-4 gap-y-1">
						<span class="w-20 text-xs text-muted-foreground">{group.label}</span>
						{#each group.rows as row (row.key)}
							{@const account = row.accountId === null ? undefined : accounts.get(row.accountId)}
							<label class="flex items-center gap-2 text-sm">
								<input
									type="checkbox"
									class="size-4 accent-primary"
									checked={row.accountId !== null && shown.includes(row.accountId)}
									onchange={(event) =>
										row.accountId !== null && toggle(row.accountId, event.currentTarget.checked)}
								/>
								<AccountDot
									name={row.label}
									color={account ? resolveAccount(account).color : null}
								/>
							</label>
						{/each}
					</div>
				{/each}
			{/if}
		</fieldset>

		<div class="overflow-x-auto">
			<table class="w-full text-sm" data-slot="balances-table">
				<caption class="sr-only">Balances at the month-ends, in {report.base_currency}</caption>
				<thead class="text-xs text-muted-foreground">
					<tr class="border-b border-border">
						<th class="sticky left-0 bg-background py-2 pr-4 text-left font-medium" scope="col"
							>{report.base_currency}</th
						>
						{#each columns as column (column.key)}
							<th class="px-3 py-2 text-right font-medium whitespace-nowrap" scope="col"
								>{column.label}</th
							>
						{/each}
					</tr>
				</thead>
				<tbody>
					<tr class="border-b border-border font-medium" data-row="net-worth">
						<th scope="row" class="sticky left-0 bg-background py-2 pr-4 text-left">
							{table.net.label}
						</th>
						{#each table.net.cells as cell, i (columns[i].key)}
							<td class="px-3 py-2 text-right whitespace-nowrap">{@render figure(cell)}</td>
						{/each}
					</tr>
					{#each table.groups as group (group.key)}
						<tr data-group={group.key}>
							<th
								scope="colgroup"
								colspan={columns.length + 1}
								class="pt-4 pb-1 text-left text-xs font-medium text-muted-foreground"
							>
								{group.label}
							</th>
						</tr>
						{#each group.rows as row (row.key)}
							<tr class="border-b border-border/60" data-row={row.key}>
								<th scope="row" class="sticky left-0 bg-background py-2 pr-4 text-left font-normal">
									{#if row.accountId !== null}
										<a
											href={`/accounts/${row.accountId}`}
											class="rounded-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
											>{row.label}</a
										>
									{:else}
										{row.label}
									{/if}
								</th>
								{#each row.cells as cell, i (columns[i].key)}
									<td class="px-3 py-2 text-right whitespace-nowrap">{@render figure(cell)}</td>
								{/each}
							</tr>
						{/each}
					{/each}
				</tbody>
			</table>
		</div>

		{#if table.unvalued.length > 0}
			<section class="flex flex-col gap-1" aria-labelledby="not-in-chart" data-slot="unvalued">
				<h2 id="not-in-chart" class="text-sm font-medium">Not in the chart</h2>
				<p class="text-xs text-muted-foreground">
					These accounts have no balance that could be valued (no usable exchange rate), so they are
					in neither the chart nor the net worth.
				</p>
				<ul class="text-sm">
					{#each table.unvalued as item (item.accountId)}
						<li class="flex items-baseline justify-between gap-3 py-1">
							<a
								href={`/accounts/${item.accountId}`}
								class="rounded-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
								>{item.name}</a
							>
							<span class="amount text-muted-foreground">{item.native}</span>
						</li>
					{/each}
				</ul>
			</section>
		{/if}
	{/if}
</div>
