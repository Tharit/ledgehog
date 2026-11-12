<script lang="ts">
	import AbsentValue from '#lib/components/common/absent-value.svelte';
	import Card from '#lib/components/common/card.svelte';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import TreeToggle from '#lib/components/common/tree-toggle.svelte';
	import { CLOSED_GROUP, type ListGroup } from '#lib/accounts/list.js';
	import { toggled } from '#lib/reports/fold.js';
	import { resolveAccountKind } from '#lib/theme/resolve.js';
	import { cn } from '#lib/utils.js';
	import AccountRow from './account-row.svelte';

	// The Accounts page's list (ux/views/account.md): a group row per kind with its number of accounts
	// and their total at today's rate, as the Balances report groups them; the groups open collapsed
	// and fold like a report's group rows. The closed accounts are a last group, muted.
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

	let expanded = $state.raw<ReadonlySet<string>>(new Set());

	// the first and last row follow the card's curve, and the last has no hairline
	const EDGE = 'first:[&>*]:rounded-t-[11px] last:[&>*]:rounded-b-[11px] last:[&>*]:border-b-0';
	const count = (n: number) => (n === 1 ? '1 account' : `${n} accounts`);
</script>

{#if groups.length === 0}
	<EmptyState title="No accounts yet" actionLabel="Add account" onaction={onadd}>
		Accounts are added here and then fed by a file, a sync, or by hand.
	</EmptyState>
{:else}
	<Card variant="flush" element="ul" data-slot="account-groups" aria-label="Accounts">
		{#each groups as group (group.key)}
			{@const open = expanded.has(group.key)}
			{@const closed = group.key === CLOSED_GROUP}
			{@const look = resolveAccountKind(group.key)}
			<li class={EDGE} data-group={group.key} data-closed={closed || undefined}>
				<div
					class={cn(
						'flex min-h-12 items-center gap-2 border-b border-border px-4 py-2',
						closed && 'text-muted-foreground'
					)}
				>
					<TreeToggle
						name={group.label}
						expanded={open}
						toggleable={group.accounts.length > 0}
						ontoggle={() => (expanded = toggled(expanded, group.key))}
					/>
					<DimensionIcon icon={look.icon} color={look.color} size="compact" />
					<span class="text-sm font-medium">{group.label}</span>
					<span class="text-xs text-muted-foreground" data-slot="group-count"
						>{count(group.accounts.length)}</span
					>
					<span class="ml-auto text-sm font-medium whitespace-nowrap" data-slot="group-total">
						{#if group.total.minor === null}
							<AbsentValue label="unvalued" explanation={group.total.note ?? ''} />
						{:else}
							<span title={group.total.note}>
								<MoneyDisplay
									minor={group.total.minor}
									currency={group.total.currency}
									{locale}
									showPlus={false}
									showCurrency
								/>
							</span>
						{/if}
					</span>
				</div>
			</li>
			{#if open}
				{#each group.accounts as account (account.id)}
					<li class={EDGE}>
						<AccountRow {account} {locale} {today} flush inset />
					</li>
				{/each}
			{/if}
		{/each}
	</Card>
{/if}
