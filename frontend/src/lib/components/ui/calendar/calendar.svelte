<script lang="ts">
	import type { DateValue } from "@internationalized/date";
	import { Calendar as CalendarPrimitive } from "bits-ui";
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import { buttonVariants } from "#lib/components/ui/button/index.js";
	import { cn } from "#lib/utils.js";
	import * as RangeCalendar from "#lib/components/ui/range-calendar/index.js";
	import CalendarDay from "./calendar-day.svelte";

	// One day chosen: the single-date sibling of the range calendar (same cell size, tokens, nav and
	// locale handling). The week starts as the locale says; arrow keys move, Enter chooses.
	let {
		ref = $bindable(null),
		value = $bindable(),
		placeholder = $bindable(),
		weekdayFormat = "short",
		class: className,
		locale = "en-US",
		disableDaysOutsideMonth = false,
		onValueChange,
		minValue,
		maxValue,
		...restProps
	}: {
		ref?: HTMLElement | null;
		value?: DateValue | undefined;
		placeholder?: DateValue | undefined;
		weekdayFormat?: CalendarPrimitive.RootProps["weekdayFormat"];
		class?: string;
		locale?: string;
		disableDaysOutsideMonth?: boolean;
		onValueChange?: (value: DateValue | undefined) => void;
		minValue?: DateValue;
		maxValue?: DateValue;
		"aria-label"?: string;
		"aria-labelledby"?: string;
	} = $props();
</script>

<CalendarPrimitive.Root
	type="single"
	bind:ref
	bind:value
	bind:placeholder
	{weekdayFormat}
	{disableDaysOutsideMonth}
	preventDeselect
	class={cn(
		"[--cell-radius:var(--radius-md)] [--cell-size:--spacing(7)] group/calendar bg-background p-3 [[data-slot=popover-content]_&]:bg-transparent",
		className
	)}
	{locale}
	{onValueChange}
	{minValue}
	{maxValue}
	{...restProps}
>
	{#snippet children({ months, weekdays })}
		<RangeCalendar.Months>
			<RangeCalendar.Nav>
				<CalendarPrimitive.PrevButton
					class={cn(
						buttonVariants({ variant: "ghost" }),
						"size-(--cell-size) bg-transparent p-0 select-none disabled:opacity-50 rtl:rotate-180"
					)}
				>
					<ChevronLeftIcon class="size-4" />
				</CalendarPrimitive.PrevButton>
				<CalendarPrimitive.NextButton
					class={cn(
						buttonVariants({ variant: "ghost" }),
						"size-(--cell-size) bg-transparent p-0 select-none disabled:opacity-50 rtl:rotate-180"
					)}
				>
					<ChevronRightIcon class="size-4" />
				</CalendarPrimitive.NextButton>
			</RangeCalendar.Nav>
			{#each months as month (month)}
				<RangeCalendar.Month>
					<CalendarPrimitive.Header
						class="flex h-(--cell-size) w-full items-center justify-center gap-1.5 text-sm font-medium"
					>
						<CalendarPrimitive.Heading />
					</CalendarPrimitive.Header>
					<CalendarPrimitive.Grid class="mt-4 flex w-full border-collapse flex-col gap-1">
						<CalendarPrimitive.GridHead>
							<CalendarPrimitive.GridRow class="flex select-none">
								{#each weekdays as weekday, i (i)}
									<CalendarPrimitive.HeadCell
										class="w-(--cell-size) rounded-md text-[0.8rem] font-normal text-muted-foreground"
									>
										{weekday.slice(0, 2)}
									</CalendarPrimitive.HeadCell>
								{/each}
							</CalendarPrimitive.GridRow>
						</CalendarPrimitive.GridHead>
						<CalendarPrimitive.GridBody>
							{#each month.weeks as weekDates (weekDates)}
								<CalendarPrimitive.GridRow class="mt-2 flex w-full">
									{#each weekDates as date (date)}
										<CalendarPrimitive.Cell
											{date}
											month={month.value}
											class="relative size-(--cell-size) p-0 text-center text-sm focus-within:z-20"
										>
											<CalendarDay />
										</CalendarPrimitive.Cell>
									{/each}
								</CalendarPrimitive.GridRow>
							{/each}
						</CalendarPrimitive.GridBody>
					</CalendarPrimitive.Grid>
				</RangeCalendar.Month>
			{/each}
		</RangeCalendar.Months>
	{/snippet}
</CalendarPrimitive.Root>
