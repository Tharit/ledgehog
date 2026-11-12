<script lang="ts">
	import { columnHeader, columnsOf, gridTemplate } from '#lib/accounts/columns.js';
	import { CLOSED_GROUP, type ListGroup } from '#lib/accounts/list.js';
	import Card from '#lib/components/common/card.svelte';
	import CardTitle from '#lib/components/common/card-title.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import { formatCount } from '#lib/format/index.js';
	import { resolveAccountKind } from '#lib/theme/resolve.js';
	import { iconFor } from '#lib/theme/icons.js';
	import { cn } from '#lib/utils.js';
	import AccountRow from './account-row.svelte';

	// The Accounts page's list (ux/views/account.md): a flush card per kind, its title row (the
	// kind's default icon, its name, its number of accounts) over the header row in one band. The cards share their columns so they line up as one
	// list; a group of more than one account ends in a total row: the sum per currency, never
	// converted. The closed accounts are a last group, "Closed", with no kind icon.
	let {
		groups,
		locale = 'en',
		today,
		onadd
	}: {
		groups: readonly ListGroup[];
		locale?: string;
		today: string;
		onadd?: () => void;
	} = $props();

	// the header's tint follows the card's curve above, the last row (or the total row) below
	const LAST_ROW = '[&>:last-child]:rounded-b-[11px] [&>:last-child]:border-b-0';
</script>

{#if groups.length === 0}
	<EmptyState title="No accounts yet" actionLabel="Add account" onaction={onadd}>
		Accounts are added here and then fed by a file, a sync, or by hand.
	</EmptyState>
{:else}
	<div class="flex flex-col gap-4" data-slot="account-groups">
		{#each groups as group (group.key)}
			{@const closed = group.key === CLOSED_GROUP}
			{@const KindIcon = closed ? null : iconFor(resolveAccountKind(group.key).icon)}
			{@const columns = columnsOf(group.investment)}
			{@const template = gridTemplate(columns)}
			{@const sumsCoded = group.sums.length > 1}
			<section
				aria-labelledby={`group-${group.key}`}
				data-group={group.key}
				data-closed={closed || undefined}
			>
				<Card variant="flush">
					<CardTitle
						id={`group-${group.key}`}
						title={group.label}
						count={formatCount(group.accounts.length, locale)}
						icon={KindIcon}
					/>
					<div role="table" aria-label={group.label} class={LAST_ROW}>
						<div
							role="row"
							class="grid h-8 items-center gap-x-3 border-b border-border bg-muted px-3 text-xs font-medium text-muted-foreground"
							style:grid-template-columns={template}
						>
							{#each columns as column (column.id)}
								<div
									role="columnheader"
									class={cn('min-w-0 truncate', column.align === 'right' && 'text-right')}
								>
									{columnHeader(column, group.currency)}
								</div>
							{/each}
						</div>
						{#each group.accounts as account (account.id)}
							<AccountRow
								{account}
								{columns}
								currency={group.currency}
								{locale}
								{today}
								showKind={closed}
							/>
						{/each}
						{#if group.accounts.length > 1}
							<div
								role="row"
								class="grid min-h-8 items-center gap-x-3 bg-muted px-3 text-xs font-medium text-muted-foreground"
								style:grid-template-columns={template}
								data-total-row
							>
								<div role="cell" class="min-w-0">Total</div>
								<div
									role="cell"
									class="[grid-column:2/-1] flex min-w-0 items-center justify-end gap-3"
									data-slot="total-sums"
								>
									{#each group.sums as sum (sum.currency)}
										<span class="text-[13px] font-normal">
											<MoneyDisplay
												minor={sum.amount}
												currency={sum.currency}
												{locale}
												showCurrency={sumsCoded}
												showPlus={false}
											/>
										</span>
									{/each}
								</div>
							</div>
						{/if}
					</div>
				</Card>
			</section>
		{/each}
	</div>
{/if}
