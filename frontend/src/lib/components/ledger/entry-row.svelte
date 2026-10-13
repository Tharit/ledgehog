<script lang="ts" module>
	/** The tags a row shows before it says "+N". */
	export const VISIBLE_TAGS = 2;
</script>

<script lang="ts">
	import AbsentValue from '#lib/components/common/absent-value.svelte';
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import ReviewBadge from '#lib/components/common/review-badge.svelte';
	import TagChip from '#lib/components/common/tag-chip.svelte';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { CHANGED_BY_YOU } from '#lib/ledger/patch.js';
	import { ENTRY_TYPE_INFO, isDerivedType } from '#lib/ledger/types.js';
	import { resolveAccount, resolveCategory, resolveTag } from '#lib/theme/resolve.js';
	import type { Entry } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';
	import { COLUMNS, GRID_TEMPLATE, ROW_GRID } from './columns.js';

	// One entry as a compact row: 32px, one line, a divider below (design §5). The cursor row has
	// the accent background and a 2px primary bar on its left edge (design §7).
	let {
		entry,
		lookups,
		locale = 'en',
		showCurrency = false,
		cursor = false,
		changed = false,
		changedTitle = CHANGED_BY_YOU,
		onselect
	}: {
		entry: Entry;
		lookups: Lookups;
		locale?: string;
		showCurrency?: boolean;
		cursor?: boolean;
		/** the user's last action took this row out of the filter; it stays until a refresh (§7) */
		changed?: boolean;
		/** why the row is marked (tooltip) */
		changedTitle?: string;
		onselect?: () => void;
	} = $props();

	// Derived entries (spec §3.9) take a fixed icon and their type's name in place of a category.
	const fixed = $derived(isDerivedType(entry.type) ? ENTRY_TYPE_INFO[entry.type!] : undefined);
	const account = $derived(lookups.accounts.get(entry.account_id));
	const counterAccount = $derived(
		entry.counter_account_id === null ? undefined : lookups.accounts.get(entry.counter_account_id)
	);
	const payee = $derived(entry.payee_id === null ? undefined : lookups.payees.get(entry.payee_id));
	const category = $derived(
		entry.category_id === null ? undefined : lookups.categories.get(entry.category_id)
	);
	const categoryLook = $derived(resolveCategory(category, lookups.categories));
	const tags = $derived(
		entry.tag_ids.flatMap((id) => {
			const tag = lookups.tags.get(id);
			return tag ? [tag] : [];
		})
	);
	const shownTags = $derived(tags.slice(0, VISIBLE_TAGS));
	const hiddenTags = $derived(tags.slice(VISIBLE_TAGS));
</script>

<!-- the keyboard is handled for the whole list by LedgerTable; a click only moves the cursor -->
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_interactive_supports_focus -->
<div
	role="row"
	data-entry-id={entry.id}
	aria-selected={cursor}
	data-cursor={cursor || undefined}
	data-changed={changed || undefined}
	title={changed ? changedTitle : undefined}
	class={cn(
		ROW_GRID,
		'group relative h-8 scroll-mt-10 border-b border-border px-3 text-[13px]',
		cursor ? 'bg-accent' : 'hover:bg-muted'
	)}
	style:grid-template-columns={GRID_TEMPLATE}
	onclick={onselect}
>
	{#if changed}
		<span class="absolute inset-y-0 left-0 w-0.5 bg-dim-ochre" aria-hidden="true"></span>
	{/if}
	{#if cursor}
		<span
			class={cn('absolute inset-y-0 w-0.5 bg-primary', changed ? 'left-0.5' : 'left-0')}
			aria-hidden="true"
		></span>
	{/if}

	{#each COLUMNS as column (column.id)}
		{#if column.id === 'date'}
			<div role="gridcell"><DateDisplay date={entry.booked_on} {locale} /></div>
		{:else if column.id === 'account'}
			<div role="gridcell" class="min-w-0">
				{#if account}
					<AccountDot name={account.name} color={resolveAccount(account).color} />
				{/if}
			</div>
		{:else if column.id === 'category'}
			<div role="gridcell" class="flex min-w-0 items-center gap-2">
				{#if fixed}
					<DimensionIcon icon={fixed.icon} color="stone" />
					<span class="truncate">{fixed.name}</span>
				{:else if entry.type === 'transfer'}
					<DimensionIcon icon={ENTRY_TYPE_INFO.transfer.icon} color="stone" />
					{#if counterAccount}
						<span class="flex min-w-0 items-center gap-1">
							<span aria-hidden="true">&rarr;</span>
							<AccountDot name={counterAccount.name} color={resolveAccount(counterAccount).color} />
						</span>
					{:else}
						<AbsentValue label="→ ?" explanation="This transfer needs a counter account" />
					{/if}
				{:else if entry.category_id !== null}
					<DimensionIcon icon={categoryLook.icon} color={categoryLook.color} />
					<span class="truncate">{category ? category.name : `Category ${entry.category_id}`}</span>
				{:else}
					<AbsentValue
						label="Unclassified"
						explanation="No category yet; entries are classified in review"
					/>
				{/if}
			</div>
		{:else if column.id === 'payee'}
			<div role="gridcell" class="min-w-0 truncate">
				{#if !fixed && payee}{payee.name}{/if}
			</div>
		{:else if column.id === 'tags'}
			<div role="gridcell" class="flex min-w-0 items-center gap-1">
				<span class="flex min-w-0 items-center gap-1 overflow-hidden">
					{#each shownTags as tag (tag.id)}
						<TagChip name={tag.name} color={resolveTag(tag).color} />
					{/each}
				</span>
				{#if hiddenTags.length > 0}
					<span
						class="shrink-0 text-xs text-muted-foreground"
						title={hiddenTags.map((tag) => tag.name).join(', ')}>+{hiddenTags.length}</span
					>
				{/if}
			</div>
		{:else if column.id === 'description'}
			<div role="gridcell" class="min-w-0 truncate">
				{#if entry.display_text}
					<span title={entry.display_text}>{entry.display_text}</span>
				{:else if !fixed}
					<AbsentValue
						label="No text"
						explanation="This entry has no description, counterparty or purpose"
					/>
				{/if}
			</div>
		{:else if column.id === 'review'}
			<div role="gridcell" class="flex items-center gap-1 overflow-hidden">
				{#if !fixed}
					{#each entry.review_flags as flag (flag)}
						<ReviewBadge {flag} />
					{/each}
				{/if}
			</div>
		{:else if column.id === 'amount'}
			<div role="gridcell">
				<MoneyDisplay
					minor={entry.amount.amount}
					currency={entry.amount.currency}
					{locale}
					{showCurrency}
				/>
			</div>
		{/if}
	{/each}
</div>
