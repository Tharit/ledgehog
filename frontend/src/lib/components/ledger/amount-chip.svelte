<script lang="ts" module>
	export type AmountPatch = {
		amount_min?: number;
		amount_max?: number;
		currency?: string;
		direction?: 'in' | 'out';
	};
</script>

<script lang="ts">
	import { untrack } from 'svelte';
	import ChoiceSelect from '#lib/components/common/choice-select.svelte';
	import Field from '#lib/components/common/field.svelte';
	import Segmented from '#lib/components/common/segmented.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { formatMoney, parseMoneyInput, type MoneyParseError } from '#lib/format/index.js';
	import FilterChip from './filter-chip.svelte';

	// The amount chip: a range of MAGNITUDES (the size of an amount, its sign ignored) in one
	// currency, optionally only money out (negative amounts) or in (positive). The API compares
	// in the currency's minor units and never converts (so a range needs its currency).
	let {
		label,
		active = false,
		amount_min,
		amount_max,
		currency,
		direction,
		currencies,
		defaultCurrency,
		locale = 'en',
		withDirection = true,
		onchange
	}: {
		label: string;
		active?: boolean;
		amount_min?: number;
		amount_max?: number;
		currency?: string;
		direction?: 'in' | 'out';
		/** the currencies to choose from */
		currencies: readonly string[];
		defaultCurrency: string;
		locale?: string;
		/** offer the in/out choice (the ledger's entries have a direction, documents do not) */
		withDirection?: boolean;
		onchange: (patch: AmountPatch) => void;
	} = $props();

	let open = $state(false);
	let minText = $state('');
	let maxText = $state('');
	let chosenCurrency = $state('');
	let chosenDirection = $state<'in' | 'out' | ''>('');
	let problem = $state('');

	const choices = $derived(
		[...new Set([...currencies, defaultCurrency, ...(currency ? [currency] : [])])].sort()
	);

	// each time the popover opens it shows the filter as it is
	$effect(() => {
		if (!open) return;
		untrack(() => {
			chosenCurrency = currency ?? defaultCurrency;
			const show = (minor: number | undefined) =>
				minor === undefined ? '' : formatMoney(minor, chosenCurrency, { locale, showPlus: false });
			minText = show(amount_min);
			maxText = show(amount_max);
			chosenDirection = direction ?? '';
			problem = '';
		});
	});

	const PARSE_PROBLEMS: Record<MoneyParseError, string> = {
		empty: 'Enter an amount',
		invalid: 'Not a valid amount',
		ambiguous: 'Ambiguous: write the decimals explicitly, as in 1,234.00',
		too_many_decimals: 'Too many decimals for this currency',
		too_large: 'Too large'
	};

	function bound(text: string): { minor?: number; problem?: string } {
		if (text.trim() === '') return {};
		const parsed = parseMoneyInput(text, chosenCurrency, locale);
		return parsed.ok ? { minor: parsed.minor } : { problem: PARSE_PROBLEMS[parsed.error] };
	}

	function apply() {
		const min = bound(minText);
		const max = bound(maxText);
		const failed = min.problem ?? max.problem;
		if (failed) {
			problem = failed;
			return;
		}
		if (min.minor !== undefined && max.minor !== undefined && min.minor > max.minor) {
			problem = 'The minimum is larger than the maximum';
			return;
		}
		const hasBound = min.minor !== undefined || max.minor !== undefined;
		onchange({
			amount_min: min.minor,
			amount_max: max.minor,
			currency: hasBound ? chosenCurrency : undefined,
			direction: chosenDirection === '' ? undefined : chosenDirection
		});
		open = false;
	}

	function clear() {
		onchange({});
		open = false;
	}

	const DIRECTIONS: { value: 'in' | 'out' | ''; label: string }[] = [
		{ value: '', label: 'Any' },
		{ value: 'out', label: 'Out' },
		{ value: 'in', label: 'In' }
	];
</script>

<FilterChip {label} {active} bind:open width="w-80">
	{#if withDirection}
		<p class="text-xs text-muted-foreground">
			Compares the size of an amount and ignores its sign. Out is money leaving an account
			(negative), In is money arriving (positive).
		</p>
		<Segmented
			label="Direction"
			role="radio"
			options={DIRECTIONS}
			value={chosenDirection}
			onchange={(direction) => (chosenDirection = direction)}
		/>
	{:else}
		<p class="text-xs text-muted-foreground">
			Compares the size of an amount and ignores its sign.
		</p>
	{/if}
	<div class="flex items-end gap-2">
		<Field label="Min">
			{#snippet children(control)}
				<Input
					{...control}
					aria-label="Minimum amount"
					inputmode="decimal"
					bind:value={minText}
					class="amount"
				/>
			{/snippet}
		</Field>
		<span class="pb-1.5 text-muted-foreground" aria-hidden="true">&ndash;</span>
		<Field label="Max">
			{#snippet children(control)}
				<Input
					{...control}
					aria-label="Maximum amount"
					inputmode="decimal"
					bind:value={maxText}
					class="amount"
				/>
			{/snippet}
		</Field>
		<Field label="Currency">
			{#snippet children(control)}
				<ChoiceSelect
					id={control.id}
					label="Currency"
					value={chosenCurrency}
					options={choices.map((code) => ({ value: code, label: code }))}
					class="w-24 bg-card"
					onchange={(next) => (chosenCurrency = next)}
				/>
			{/snippet}
		</Field>
	</div>
	{#if problem}
		<p role="alert" class="text-xs text-destructive">{problem}</p>
	{/if}
	<div class="flex items-center justify-between">
		<Button variant="ghost" onclick={clear}>Clear</Button>
		<Button onclick={apply}>Apply</Button>
	</div>
</FilterChip>
