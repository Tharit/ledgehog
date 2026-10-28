<script lang="ts">
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import ReviewBadge from '#lib/components/common/review-badge.svelte';
	import { amountHeader, columnCurrency } from '#lib/format/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { FIELD_LABELS, type ConditionField } from '#lib/rules/conditions.js';
	import { sourceText } from '#lib/rules/preview.js';
	import type { RulePreviewRow, RuleSets } from '#lib/rules/types.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import { describeKey, asKey, knownRules } from '#lib/units/evidence.js';
	import { unitPanel } from '#lib/units/panel-instance.js';
	import { registerUnitSource } from '#lib/units/sources.js';
	import RuleTarget from './rule-target.svelte';

	// The entries of one preview list as a table with headers in two groups. "Entry" is what the
	// row is: booked date, account, amount and what the rule's target holds now with its basis.
	// "Source transaction" is what the rule reads: the counterparty name always, and one column
	// for every other field the conditions read. A row opens the review panel on its entry (click or
	// Enter), and the panel steps through this table's rows. Everything shown is what the server sent. A table may be wider than the
	// screen and scrolls inside its own container.
	let {
		rows,
		columns,
		sets,
		lookups,
		ruleName,
		label,
		locale = 'en'
	}: {
		rows: readonly RulePreviewRow[];
		/** the source fields to show, in order */
		columns: readonly ConditionField[];
		sets: RuleSets;
		lookups: Lookups;
		/** a rule's name by id, for the rule that takes precedence and for keys */
		ruleName: (id: number) => string | undefined;
		/** the accessible name of the table */
		label: string;
		locale?: string;
	} = $props();

	// rows can come from accounts of several currencies: one shared currency heads the column,
	// mixed ones are coded in every cell (patterns §2)
	const amountCode = $derived(columnCurrency(rows.map((r) => r.amount.currency)));

	const rules = $derived(knownRules(ruleName));

	function open(entryId: number, row: HTMLElement | null) {
		registerUnitSource({
			neighbour: (id, dir) => {
				const at = rows.findIndex((r) => r.entry_id === id);
				return at < 0 ? null : (rows[at + dir]?.entry_id ?? null);
			},
			// the table has no cursor: the row of the unit shown is scrolled into view
			reveal: (id) => {
				const row = document.querySelector(`[data-entry-id="${id}"]`);
				if (!row || !rows.some((r) => r.entry_id === id)) return false;
				row.scrollIntoView?.({ block: 'nearest' });
				return true;
			},
			patch: () => {}
		});
		unitPanel.open(entryId, row);
	}

	function shadow(row: RulePreviewRow): string | null {
		return row.shadowed_by_rule_id === null
			? null
			: (ruleName(row.shadowed_by_rule_id) ?? `#${row.shadowed_by_rule_id}`);
	}
</script>

<div class="overflow-x-auto rounded-lg border" data-slot="preview-table">
	<table class="w-full border-collapse text-[13px]" aria-label={label}>
		<thead class="bg-muted text-xs font-medium text-muted-foreground">
			<tr>
				<th scope="colgroup" colspan="4" class="px-3 pt-1.5 text-left font-medium">Entry</th>
				<th
					scope="colgroup"
					colspan={columns.length}
					class="border-l px-3 pt-1.5 text-left font-medium"
				>
					Source transaction
				</th>
			</tr>
			<tr class="border-b">
				<th scope="col" class="px-3 pb-1.5 text-left font-medium whitespace-nowrap">Booked</th>
				<th scope="col" class="px-3 pb-1.5 text-left font-medium whitespace-nowrap">Account</th>
				<th scope="col" class="px-3 pb-1.5 text-right font-medium whitespace-nowrap">
					{amountHeader('Amount', amountCode)}
				</th>
				<th scope="col" class="px-3 pb-1.5 text-left font-medium whitespace-nowrap">Currently</th>
				{#each columns as field, i (field)}
					<th
						scope="col"
						class={['min-w-40 px-3 pb-1.5 text-left font-medium', i === 0 && 'border-l']}
					>
						{FIELD_LABELS[field]}
					</th>
				{/each}
			</tr>
		</thead>
		<tbody
			class="[&_td]:px-3 [&_td]:py-1.5 [&_td]:align-top [&_tr]:border-b [&_tr:last-child]:border-b-0"
		>
			{#each rows as row (row.entry_id)}
				{@const account = lookups.accounts.get(row.account_id)}
				{@const basis = describeKey(asKey(row.current_key), rules, locale)}
				{@const taken = shadow(row)}
				<!-- the keyboard path is Enter on the focused row; a click is the mouse path -->
				<tr
					data-entry-id={row.entry_id}
					tabindex="0"
					class="cursor-default hover:bg-row-hover focus-visible:bg-accent focus-visible:outline-none"
					onclick={(event) => open(row.entry_id, event.currentTarget)}
					onkeydown={(event) => {
						if (event.key === 'Enter' && event.target === event.currentTarget) {
							event.preventDefault();
							open(row.entry_id, event.currentTarget);
						}
					}}
				>
					<td>
						<span class="flex items-center gap-2">
							<DateDisplay date={row.booked_on} {locale} />
							{#if !row.confirmed}<ReviewBadge flag="unconfirmed" />{/if}
						</span>
					</td>
					<td class="whitespace-nowrap">
						{#if account}<AccountDot
								name={account.name}
								color={resolveAccount(account).color}
							/>{/if}
					</td>
					<td class="text-right whitespace-nowrap">
						<MoneyDisplay
							minor={row.amount.amount}
							currency={row.amount.currency}
							{locale}
							showCurrency={amountCode === null}
						/>
					</td>
					<td class="min-w-44">
						{#if row.current_value === null}
							<span class="text-muted-foreground">None yet</span>
						{:else}
							<RuleTarget {sets} id={row.current_value} {lookups} />
						{/if}
						{#if basis}
							<span
								class={['block text-xs text-muted-foreground', basis.proposal && 'italic']}
								data-slot="preview-basis"
							>
								{basis.text}
							</span>
						{/if}
						{#if taken}
							<span class="block text-xs text-muted-foreground italic" data-slot="preview-shadow">
								Rule “{taken}” takes precedence
							</span>
						{/if}
					</td>
					{#each columns as field, i (field)}
						{@const text = sourceText(row, field)}
						<td class={['max-w-72 break-words', i === 0 && 'border-l']}>
							{#if text !== null}
								{text}
							{:else}
								<span
									class="text-muted-foreground"
									title={row.source
										? 'The source transaction has nothing here'
										: 'No source transaction'}>&mdash;</span
								>
							{/if}
						</td>
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
</div>
