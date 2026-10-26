<script lang="ts">
	import { onDestroy, untrack } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import AmountChip, { type AmountPatch } from '#lib/components/ledger/amount-chip.svelte';
	import DateChip from '#lib/components/ledger/date-chip.svelte';
	import OptionsChip, { type ChipOption } from '#lib/components/ledger/options-chip.svelte';
	import {
		describeDocumentFilter,
		emptyDocumentFilter,
		isEmptyDocumentFilter,
		type DocumentFilterKey
	} from '#lib/documents/filter.js';
	import type { DocumentFilter } from '#lib/types/domain.js';

	// The documents filter bar: chips for provider, date and amount, plus a text box
	// bound to `q`, in the manner of the ledger's. It owns no filter state: it shows `filter` and
	// reports every change through `onchange`; the page keeps the filter in the URL.
	let {
		filter,
		providers,
		currencies,
		locale = 'en',
		today,
		baseCurrency,
		onchange
	}: {
		filter: DocumentFilter;
		/** the providers to choose from */
		providers: readonly string[];
		/** the currencies an amount range can be in */
		currencies: readonly string[];
		locale?: string;
		today: string;
		baseCurrency: string;
		onchange: (next: DocumentFilter) => void;
	} = $props();

	const SEARCH_DELAY_MS = 250;

	const parts = $derived(describeDocumentFilter(filter, locale));
	function label(key: DocumentFilterKey, fallback: string): string {
		return parts.find((part) => part.key === key)?.label ?? fallback;
	}

	function update(patch: Partial<DocumentFilter>) {
		onchange({ ...filter, ...patch });
	}

	const providerOptions = $derived<ChipOption<string>[]>(
		providers.map((provider) => ({ value: provider, label: provider }))
	);

	function updateAmount(patch: AmountPatch) {
		update({
			amount_min: patch.amount_min,
			amount_max: patch.amount_max,
			currency: patch.currency
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

	function clearAll() {
		clearTimeout(timer);
		text = '';
		lastSent = '';
		onchange(emptyDocumentFilter());
	}

	onDestroy(() => clearTimeout(timer));
</script>

<div class="flex flex-wrap items-center gap-2" role="search" aria-label="Filter documents">
	<OptionsChip
		label={label('provider', 'All providers')}
		heading="Providers"
		options={providerOptions}
		selected={filter.provider}
		emptyText="No document importer is set up"
		onchange={(provider) => update({ provider })}
	/>
	<DateChip
		label={label('date', 'Any date')}
		from={filter.from}
		to={filter.to}
		{today}
		{locale}
		onchange={(from, to) => update({ from, to })}
	/>
	<AmountChip
		label={label('amount', 'Amount')}
		active={parts.some((part) => part.key === 'amount')}
		amount_min={filter.amount_min}
		amount_max={filter.amount_max}
		currency={filter.currency}
		{currencies}
		defaultCurrency={baseCurrency}
		{locale}
		withDirection={false}
		onchange={updateAmount}
	/>
	<Input
		bind:value={text}
		type="text"
		placeholder="Filter…"
		aria-label="Filter documents by text"
		class="w-56 rounded-full bg-muted"
		oninput={typed}
		onkeydown={(event) => {
			if (event.key === 'Enter') send();
			if (event.key === 'Escape') (event.currentTarget as HTMLElement).blur();
		}}
	/>
	{#if !isEmptyDocumentFilter(filter)}
		<Button variant="ghost" onclick={clearAll}>Clear</Button>
	{/if}
</div>
