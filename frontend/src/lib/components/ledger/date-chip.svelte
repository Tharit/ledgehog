<script lang="ts">
	import { parseDate, type DateValue } from '@internationalized/date';
	import { Button } from '#lib/components/ui/button/index.js';
	import { RangeCalendar } from '#lib/components/ui/range-calendar/index.js';
	import { datePresets } from '#lib/ledger/presets.js';
	import type { IsoDate } from '#lib/types/domain.js';
	import FilterChip from './filter-chip.svelte';

	// The date range chip: presets computed from the household's today, and a range calendar.
	// Both ends are inclusive and the label says so ("1 Oct – 11 Oct").
	let {
		label,
		from,
		to,
		today,
		locale = 'en',
		onchange
	}: {
		label: string;
		from?: IsoDate;
		to?: IsoDate;
		today: IsoDate;
		locale?: string;
		onchange: (from: IsoDate | undefined, to: IsoDate | undefined) => void;
	} = $props();

	let open = $state(false);
	// follows the filter (a preset, Clear, Back); the calendar writes to it while a range is picked
	let range = $derived<{ start: DateValue | undefined; end: DateValue | undefined }>({
		start: from ? parseDate(from) : undefined,
		end: to ? parseDate(to) : undefined
	});

	const presets = $derived(datePresets(today));

	function apply(start: IsoDate | undefined, end: IsoDate | undefined) {
		onchange(start, end);
		open = false;
	}

	function picked(value: { start: DateValue | undefined; end: DateValue | undefined }) {
		// a range is complete once both ends are chosen
		if (value.start && value.end) apply(value.start.toString(), value.end.toString());
	}
</script>

<FilterChip {label} active={Boolean(from || to)} bind:open width="w-auto">
	<div class="flex flex-wrap gap-1">
		{#each presets as preset (preset.id)}
			<Button
				variant={preset.from === from && preset.to === to ? 'secondary' : 'outline'}
				size="sm"
				onclick={() => apply(preset.from, preset.to)}>{preset.label}</Button
			>
		{/each}
	</div>
	<RangeCalendar bind:value={range} {locale} onValueChange={picked} />
	<div class="flex items-center justify-between">
		<span class="text-xs text-muted-foreground">Both days are included</span>
		{#if from || to}
			<Button variant="ghost" size="xs" onclick={() => apply(undefined, undefined)}>Clear</Button>
		{/if}
	</div>
</FilterChip>
