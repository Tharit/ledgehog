<script lang="ts">
	import { parseDate, type DateValue } from '@internationalized/date';
	import CalendarIcon from '@lucide/svelte/icons/calendar';
	import { Calendar } from '#lib/components/ui/calendar/index.js';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import { formatDate, type IsoDate } from '#lib/format/index.js';
	import { cn } from '#lib/utils.js';

	// One calendar date chosen (patterns §11.2): a button showing the date, and a popover with a
	// single-day calendar, the date chip's pattern for one day. The value is the ISO date string;
	// choosing a day sets it and closes the popover. Spread the Field's control props onto it.
	let {
		value = $bindable(''),
		label,
		locale = 'en',
		disabled = false,
		onchange,
		...control
	}: {
		value?: IsoDate;
		/** the accessible name of the button ("Date") */
		label: string;
		locale?: string;
		disabled?: boolean;
		onchange?: (value: IsoDate) => void;
		id?: string;
		'aria-describedby'?: string;
		'aria-invalid'?: boolean;
	} = $props();

	let open = $state(false);
	function toCalendar(iso: IsoDate): DateValue | undefined {
		try {
			return iso ? parseDate(iso) : undefined;
		} catch {
			return undefined;
		}
	}
	// follows the value; the calendar writes to it when a day is chosen
	let day = $derived<DateValue | undefined>(toCalendar(value));
	const text = $derived.by(() => {
		try {
			return value ? formatDate(value, locale) : '';
		} catch {
			return value;
		}
	});

	function picked(next: DateValue | undefined) {
		if (!next) return;
		value = next.toString();
		onchange?.(value);
		open = false;
	}
</script>

<Popover.Root bind:open>
	<Popover.Trigger
		{...control}
		aria-label={label}
		aria-invalid={control['aria-invalid'] || undefined}
		{disabled}
		data-slot="date-field"
		class={cn(
			'flex h-8 w-full min-w-0 items-center justify-between gap-2 rounded-lg border border-input bg-transparent px-2.5 text-left text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive dark:bg-input/30'
		)}
	>
		<span class="truncate">{text}</span>
		<CalendarIcon
			size={14}
			strokeWidth={1.75}
			class="shrink-0 text-muted-foreground"
			aria-hidden="true"
		/>
	</Popover.Trigger>
	<Popover.Content align="start" class="w-auto p-0" aria-label={`Choose ${label.toLowerCase()}`}>
		<Calendar bind:value={day} {locale} onValueChange={picked} aria-label={label} />
	</Popover.Content>
</Popover.Root>
