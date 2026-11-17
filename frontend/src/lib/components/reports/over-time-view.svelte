<script lang="ts">
	import { accountStack, categoryStack, incomeExpensePoints } from '#lib/reports/charts.js';
	import type { Scope } from '#lib/reports/links.js';
	import type { OverTime } from '#lib/reports/shapes.js';
	import { accountTrendTable, categoryTrendTable, savingsTable } from '#lib/reports/tables.js';
	import type { Account, Category } from '#lib/types/domain.js';
	import Card from '#lib/components/common/card.svelte';
	import AccountTrendTable from './account-trend-table.svelte';
	import CategoryStackChart from './category-stack-chart.svelte';
	import CategoryTrendTable from './category-trend-table.svelte';
	import IncomeExpenseChart from './income-expense-chart.svelte';
	import SavingsTable from './savings-table.svelte';

	// *Over time* (reports.md): a range cut into months, quarters or years. The answer says which mode
	// it is in (its fields are the mode's): *Income and expense* has `savings`, *By category* has
	// `categories`, *By account* has `accounts`. Every chart has its table beneath it as the
	// readable data.
	let {
		report,
		categories,
		accounts = new Map(),
		scope,
		locale = 'en'
	}: {
		report: OverTime;
		categories: ReadonlyMap<number, Category>;
		/** the accounts of the by-account mode */
		accounts?: ReadonlyMap<number, Account>;
		scope: Scope;
		locale?: string;
	} = $props();

	// the kind's sign: income and transfers in are positive, expense and transfers out negative
	const sign = $derived(report.kind === 'income' || report.kind === 'transfer_in' ? 1 : -1);
</script>

{#if report.savings}
	{@const points = incomeExpensePoints(report.periods, report.savings, report.step, locale)}
	{@const table = savingsTable(report, categories, scope, locale)}
	<div class="flex flex-col gap-6">
		<Card>
			<IncomeExpenseChart {points} currency={report.base_currency} {locale} />
		</Card>
		<Card variant="flush">
			<SavingsTable
				columns={table.columns}
				rows={table.rows}
				currency={report.base_currency}
				{locale}
			/>
		</Card>
	</div>
{:else if report.categories}
	{@const stack = categoryStack(report, categories, locale)}
	{@const table = categoryTrendTable(report, categories, scope, locale)}
	<div class="flex flex-col gap-6">
		{#if stack.series.length > 0}
			<Card>
				<CategoryStackChart
					series={stack.series}
					rows={stack.rows}
					currency={report.base_currency}
					{sign}
					{locale}
				/>
			</Card>
		{/if}
		{#if table.rows.length === 0}
			<p class="text-sm text-muted-foreground" data-slot="nothing">Nothing in this period.</p>
		{:else}
			<Card variant="flush">
				<CategoryTrendTable
					columns={table.columns}
					rows={table.rows}
					total={table.total}
					{categories}
					currency={report.base_currency}
					{locale}
				/>
			</Card>
		{/if}
	</div>
{:else if report.accounts}
	{@const stack = accountStack(report, accounts, locale)}
	{@const table = accountTrendTable(report, accounts, categories, scope, locale)}
	<div class="flex flex-col gap-6">
		{#if stack.series.length > 0}
			<Card>
				<CategoryStackChart
					series={stack.series}
					rows={stack.rows}
					currency={report.base_currency}
					{sign}
					{locale}
				/>
			</Card>
		{/if}
		{#if table.rows.length === 0}
			<p class="text-sm text-muted-foreground" data-slot="nothing">Nothing in this period.</p>
		{:else}
			<Card variant="flush">
				<AccountTrendTable
					columns={table.columns}
					rows={table.rows}
					total={table.total}
					{accounts}
					currency={report.base_currency}
					{locale}
				/>
			</Card>
		{/if}
	</div>
{/if}
