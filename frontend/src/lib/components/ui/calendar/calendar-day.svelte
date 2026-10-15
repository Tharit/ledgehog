<script lang="ts">
	import { Calendar as CalendarPrimitive } from "bits-ui";
	import { cn } from "#lib/utils.js";

	let {
		ref = $bindable(null),
		class: className,
		...restProps
	}: CalendarPrimitive.DayProps = $props();
</script>

<CalendarPrimitive.Day
	bind:ref
	class={cn(
		"flex size-(--cell-size) flex-col items-center justify-center gap-1 rounded-(--cell-radius) p-0 leading-none font-normal whitespace-nowrap select-none",
		"not-data-selected:hover:bg-accent/50 not-data-selected:hover:text-accent-foreground",
		"[&[data-today]:not([data-selected])]:bg-accent [&[data-today]:not([data-selected])]:text-accent-foreground",
		"data-selected:bg-primary data-selected:text-primary-foreground data-selected:hover:text-foreground",
		"[&[data-outside-month]:not([data-selected])]:text-muted-foreground",
		"data-[disabled]:pointer-events-none data-[disabled]:text-muted-foreground data-[disabled]:opacity-50",
		"data-[unavailable]:line-through",
		"focus:relative focus:border-ring focus:ring-ring/50",
		className
	)}
	{...restProps}
/>
