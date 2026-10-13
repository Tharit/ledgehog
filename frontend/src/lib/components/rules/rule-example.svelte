<script lang="ts">
	import AbsentValue from '#lib/components/common/absent-value.svelte';
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { NO_SOURCE_NOTE, sourceRows } from '#lib/rules/example.js';
	import type { RuleExampleStore } from '#lib/stores/rule-example.svelte.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import ExampleFind from './example-find.svelte';

	// The example: an entry to look at while writing the conditions. Nothing is filled in from it
	// and it changes nothing that is saved. Without one there is the find box; with one, a
	// read-only table of what a rule can read from its source transaction, and "Change" / "Clear".
	let {
		store,
		lookups,
		locale = 'en'
	}: { store: RuleExampleStore; lookups: Lookups; locale?: string } = $props();

	const entry = $derived(store.entry);
	const rows = $derived(entry ? sourceRows(entry) : null);
	const account = $derived(entry ? lookups.accounts.get(entry.account_id) : undefined);
</script>

<section class="flex flex-col gap-3" aria-labelledby="rule-example-title" data-slot="rule-example">
	<div class="flex flex-wrap items-center justify-between gap-2">
		<h3 id="rule-example-title" class="text-sm font-semibold">Example</h3>
		{#if entry}
			<div class="flex items-center gap-2">
				<Button variant="outline" disabled={store.finding} onclick={() => store.change()}>
					Change
				</Button>
				<Button variant="outline" onclick={() => store.clear()}>Clear</Button>
			</div>
		{/if}
	</div>
	<p class="text-xs text-muted-foreground">
		An entry to look at while you write the conditions. Nothing is filled in from it and it is not
		saved with the rule.
	</p>

	{#if store.loadStatus === 'loading'}
		<p class="text-sm text-muted-foreground" role="status" aria-busy="true">Loading the example…</p>
	{:else if store.loadStatus === 'missing'}
		<p class="text-sm text-muted-foreground" role="status">
			The example entry was not found. Choose another.
		</p>
	{:else if store.loadStatus === 'error'}
		<div class="flex items-center gap-3 text-sm" role="status">
			<span class="text-muted-foreground">The example could not be loaded.</span>
			<Button variant="outline" onclick={() => store.init()}>Try again</Button>
		</div>
	{/if}

	{#if store.finding}
		<ExampleFind {store} {locale} />
		{#if entry}
			<div>
				<Button variant="outline" onclick={() => store.cancelFind()}>Cancel</Button>
			</div>
		{/if}
	{/if}

	{#if entry}
		<div class="overflow-x-auto rounded-lg border" data-slot="example-table">
			<table class="w-full text-[13px]">
				<caption class="sr-only">The example entry</caption>
				<thead class="bg-muted text-xs font-medium text-muted-foreground">
					<tr>
						<th scope="col" class="w-44 px-3 py-1 text-left font-medium">Field</th>
						<th scope="col" class="px-3 py-1 text-left font-medium">Value</th>
					</tr>
				</thead>
				<tbody class="[&_td]:px-3 [&_td]:py-1.5 [&_th]:px-3 [&_th]:py-1.5 [&_tr]:border-t">
					<tr>
						<th scope="row" class="text-left align-top font-normal text-muted-foreground">
							Booked
						</th>
						<td><DateDisplay date={entry.booked_on} {locale} /></td>
					</tr>
					<tr>
						<th scope="row" class="text-left align-top font-normal text-muted-foreground">
							Amount
						</th>
						<td>
							<MoneyDisplay
								class="inline"
								minor={entry.amount.amount}
								currency={entry.amount.currency}
								{locale}
								showCurrency
							/>
						</td>
					</tr>
					<tr>
						<th scope="row" class="text-left align-top font-normal text-muted-foreground">
							Account
						</th>
						<td>
							{#if account}
								<AccountDot name={account.name} color={resolveAccount(account).color} />
							{:else}
								<AbsentValue label="Unknown account" explanation="Not in the loaded list" />
							{/if}
						</td>
					</tr>
					{#if rows}
						{#each rows as row (row.field)}
							<tr data-field={row.field}>
								<th scope="row" class="text-left align-top font-normal text-muted-foreground">
									{row.label}
								</th>
								<td class="break-words whitespace-pre-wrap">
									{#if row.value !== null}
										{row.value}
									{:else}
										<AbsentValue
											label="None"
											explanation="The source transaction has nothing in this field"
										/>
									{/if}
								</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
		</div>
		{#if !rows}
			<p class="text-sm text-muted-foreground" data-slot="example-no-source">{NO_SOURCE_NOTE}</p>
		{/if}
	{/if}
</section>
