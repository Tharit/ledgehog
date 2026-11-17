<script lang="ts">
	import Card from '#lib/components/common/card.svelte';
	import type { Scope } from '#lib/reports/links.js';
	import { accountSankey } from '#lib/reports/sankey.js';
	import type { ByAccount } from '#lib/reports/types.js';
	import type { Account, Category } from '#lib/types/domain.js';
	import AccountSankey from './account-sankey.svelte';
	import ByAccountTable from './by-account-table.svelte';
	import FigureLink from './figure-link.svelte';

	// *By account* (reports.md, Tab 2): a sankey from the income categories through the accounts
	// that received and the accounts that paid to the expense categories, with what could not be
	// drawn named beneath it, and the table as its readable data.
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

	const chart = $derived(accountSankey(report, categories, accounts, scope));
	const nothing = $derived(
		report.income.categories.length === 0 &&
			report.expense.categories.length === 0 &&
			report.unclassified_in.accounts.length === 0 &&
			report.unclassified_out.accounts.length === 0 &&
			report.reconciliations.accounts.length === 0 &&
			report.transfers.length === 0
	);
</script>

{#if nothing}
	<p class="text-sm text-muted-foreground" data-slot="nothing">
		Nothing in this period{scope.tagIds.length > 0 ? ' with these filters' : ''}.
	</p>
{:else}
	<div class="flex flex-col gap-8">
		{#if chart.links.length > 0}
			<Card data-slot="sankey-section">
				<AccountSankey model={chart} {locale} />
			</Card>
		{/if}
		{#if chart.notes.opposite.length > 0}
			<p class="text-sm text-muted-foreground" data-slot="opposite-note">
				Not in the chart, since their net is of the other sign:
				{#each chart.notes.opposite as item, i (item.key)}
					{i > 0 ? ', ' : ''}{item.from} to {item.to}
					(<FigureLink line={item.line} href={item.href} {locale} />){/each}.
			</p>
		{/if}

		<Card variant="flush">
			<ByAccountTable {report} {categories} {accounts} {scope} {locale} />
		</Card>
	</div>
{/if}
