<script lang="ts">
	import { onDestroy, untrack, type Snippet } from 'svelte';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { describeFilter, type FilterKey } from '#lib/ledger/describe.js';
	import { emptyFilter, ENTRY_TYPES, isEmpty } from '#lib/ledger/filter.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { ENTRY_TYPE_INFO } from '#lib/ledger/types.js';
	import { REVIEW_FLAG_INFO, REVIEW_FLAG_ORDER } from '#lib/ledger/review.js';
	import {
		categoryPath,
		resolveAccount,
		resolveCategory,
		resolvePayee,
		resolveTag
	} from '#lib/theme/resolve.js';
	import type { EntryFilter } from '#lib/types/domain.js';
	import AmountChip, { type AmountPatch } from './amount-chip.svelte';
	import DateChip from './date-chip.svelte';
	import OptionsChip, { type ChipOption } from './options-chip.svelte';

	// The filter bar (decision C1): chips for date, account, category, payee, tag, review state and
	// amount, plus a text box bound to `q`. It owns no filter state: it shows `filter` and reports
	// every change through `onchange`; the page keeps the filter in the URL.
	let {
		filter,
		lookups,
		locale = 'en',
		today,
		baseCurrency,
		searchEl = $bindable(null),
		onchange,
		ondown,
		exportHref,
		trailing
	}: {
		filter: EntryFilter;
		lookups: Lookups;
		locale?: string;
		/** the household's today, for the date presets */
		today: string;
		baseCurrency: string;
		/** the text box, so `/` can focus it */
		searchEl?: HTMLInputElement | null;
		onchange: (next: EntryFilter) => void;
		/** `↓` in the text box: the keyboard moves to the list */
		ondown?: () => void;
		/** where "Export CSV" goes: the CSV of the current filter; the action is left out without it */
		exportHref?: string;
		/** the "Tag all N…" action, at the end of the bar */
		trailing?: Snippet;
	} = $props();

	const SEARCH_DELAY_MS = 250;

	const parts = $derived(describeFilter(filter, { lookups, locale }));
	function label(key: FilterKey, fallback: string): string {
		return parts.find((part) => part.key === key)?.label ?? fallback;
	}

	function update(patch: Partial<EntryFilter>) {
		onchange({ ...filter, ...patch });
	}

	const accountOptions = $derived<ChipOption<number>[]>(
		[...lookups.accounts.values()]
			.sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name))
			.map((a) => ({ value: a.id, label: a.name, color: resolveAccount(a).color }))
	);
	const categoryOptions = $derived<ChipOption<number>[]>(
		[...lookups.categories.values()]
			.map((c) => ({
				value: c.id,
				label: categoryPath(c, lookups.categories),
				color: resolveCategory(c, lookups.categories).color
			}))
			.sort((a, b) => a.label.localeCompare(b.label))
	);
	const payeeOptions = $derived<ChipOption<number>[]>(
		[...lookups.payees.values()]
			.sort((a, b) => a.name.localeCompare(b.name))
			.map((p) => ({ value: p.id, label: p.name, color: resolvePayee(p).color }))
	);
	const tagOptions = $derived<ChipOption<number>[]>(
		[...lookups.tags.values()]
			.sort((a, b) => a.name.localeCompare(b.name))
			.map((t) => ({ value: t.id, label: t.name, color: resolveTag(t).color }))
	);
	const flagOptions: ChipOption<string>[] = REVIEW_FLAG_ORDER.map((flag) => ({
		value: flag,
		label: REVIEW_FLAG_INFO[flag].name,
		hint: REVIEW_FLAG_INFO[flag].sentence,
		flag
	}));
	// the category chip also holds the type: a type is shown in the category column
	const categoryLabel = $derived.by(() => {
		const category = parts.find((part) => part.key === 'category')?.label;
		const type = parts.find((part) => part.key === 'type')?.label;
		return [category, type].filter(Boolean).join(' · ') || 'All categories';
	});

	function toggleType(type: string, checked: boolean) {
		const rest = filter.type.filter((t) => t !== type);
		update({ type: checked ? [...rest, type] : rest });
	}
	const currencies = $derived([...new Set([...lookups.accounts.values()].map((a) => a.currency))]);

	function updateAmount(patch: AmountPatch) {
		update({
			amount_min: patch.amount_min,
			amount_max: patch.amount_max,
			currency: patch.currency,
			direction: patch.direction
		});
	}

	// the text box: changes are sent after a short pause, Enter sends at once
	let text = $state(untrack(() => filter.q));
	let lastSent = untrack(() => filter.q);
	let timer: ReturnType<typeof setTimeout> | undefined;

	// follow the filter when it changes from outside (Clear, Back, a link)
	$effect(() => {
		const q = filter.q;
		if (q !== lastSent) {
			lastSent = q;
			text = q;
		}
	});

	function send() {
		clearTimeout(timer);
		const next = text.trim();
		if (next === lastSent) return;
		lastSent = next;
		update({ q: next });
	}

	function typed() {
		clearTimeout(timer);
		timer = setTimeout(send, SEARCH_DELAY_MS);
	}

	function onsearchkeydown(event: KeyboardEvent) {
		if (event.key === 'Enter') send();
		if (event.key === 'Escape') (event.currentTarget as HTMLElement).blur();
		if (event.key === 'ArrowDown') {
			event.preventDefault();
			ondown?.();
		}
	}

	function clearAll() {
		clearTimeout(timer);
		text = '';
		lastSent = '';
		onchange(emptyFilter());
	}

	onDestroy(() => clearTimeout(timer));
</script>

<div class="flex flex-wrap items-center gap-2" role="search" aria-label="Filter entries">
	<DateChip
		label={label('date', 'Any date')}
		from={filter.from}
		to={filter.to}
		{today}
		{locale}
		onchange={(from, to) => update({ from, to })}
	/>
	<OptionsChip
		label={label('account', 'All accounts')}
		heading="Accounts"
		options={accountOptions}
		selected={filter.account_id}
		emptyText="No accounts yet"
		onchange={(account_id) => update({ account_id })}
	/>
	<OptionsChip
		label={categoryLabel}
		heading="Categories"
		options={categoryOptions}
		selected={filter.category_id}
		active={filter.category_id.length > 0 || filter.uncategorised || filter.type.length > 0}
		emptyText="No categories yet"
		manageHref="/settings/categories"
		onchange={(category_id) => update({ category_id })}
	>
		{#snippet footer()}
			<div class="mt-1 flex flex-col gap-0.5 border-t border-border pt-2">
				<div class="flex items-center justify-between">
					<span class="text-xs font-medium text-muted-foreground">Type</span>
					{#if filter.type.length > 0}
						<Button variant="ghost" size="xs" onclick={() => update({ type: [] })}>Clear</Button>
					{/if}
				</div>
				<ul class="-mx-1" aria-label="Type">
					{#each ENTRY_TYPES as type (type)}
						<li>
							<label
								class="flex h-8 items-center gap-2 rounded-md px-1.5 text-[13px] hover:bg-row-hover"
							>
								<input
									type="checkbox"
									class="size-4 shrink-0 accent-primary"
									checked={filter.type.includes(type)}
									onchange={(event) => toggleType(type, event.currentTarget.checked)}
								/>
								<DimensionIcon icon={ENTRY_TYPE_INFO[type].icon} color="stone" />
								<span class="truncate">{ENTRY_TYPE_INFO[type].name}</span>
							</label>
						</li>
					{/each}
				</ul>
			</div>
			<div class="mt-1 flex flex-col gap-1 border-t border-border pt-2 text-[13px]">
				<label class="flex items-center gap-2">
					<input
						type="checkbox"
						class="size-4 accent-primary"
						checked={!filter.category_descendants}
						disabled={filter.category_id.length === 0}
						onchange={(event) => update({ category_descendants: !event.currentTarget.checked })}
					/>
					Exact: not its subcategories
				</label>
				<label class="flex items-center gap-2">
					<input
						type="checkbox"
						class="size-4 accent-primary"
						checked={filter.uncategorised}
						onchange={(event) => update({ uncategorised: event.currentTarget.checked })}
					/>
					Include entries without a category
				</label>
			</div>
		{/snippet}
	</OptionsChip>
	<OptionsChip
		label={label('payee', 'All payees')}
		heading="Payees"
		options={payeeOptions}
		selected={filter.payee_id}
		emptyText="No payees yet"
		manageHref="/settings/payees"
		onchange={(payee_id) => update({ payee_id })}
	/>
	<OptionsChip
		label={label('tag', 'Tags')}
		heading="Tags"
		options={tagOptions}
		selected={filter.tag_id}
		emptyText="No tags yet"
		onchange={(tag_id) => update({ tag_id })}
	/>
	<OptionsChip
		label={label('flag', 'Review')}
		heading="Review state"
		options={flagOptions}
		selected={filter.flag}
		onchange={(flag) => update({ flag })}
	/>
	<AmountChip
		label={label('amount', 'Amount')}
		active={parts.some((part) => part.key === 'amount')}
		amount_min={filter.amount_min}
		amount_max={filter.amount_max}
		currency={filter.currency}
		direction={filter.direction}
		{currencies}
		defaultCurrency={baseCurrency}
		{locale}
		onchange={updateAmount}
	/>
	<Input
		bind:ref={searchEl}
		bind:value={text}
		type="text"
		placeholder="Filter…"
		aria-label="Filter entries by text"
		class="w-56 rounded-full bg-muted"
		oninput={typed}
		onkeydown={onsearchkeydown}
	/>
	{#if !isEmpty(filter)}
		<Button variant="ghost" onclick={clearAll}>Clear</Button>
	{/if}
	{#if exportHref}
		<!-- a plain link to the server's CSV of this filter; the router must leave it to the browser -->
		<Button variant="secondary" href={exportHref} data-sveltekit-reload>Export CSV</Button>
	{/if}
	{@render trailing?.()}
</div>
