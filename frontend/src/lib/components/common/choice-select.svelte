<script lang="ts">
	import ChevronsUpDownIcon from '@lucide/svelte/icons/chevrons-up-down';
	import Picker, { type PickerItem } from '#lib/components/common/picker.svelte';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import { cn } from '#lib/utils.js';

	// One value chosen from a short fixed list: the shared picker in a popover, the same trigger as
	// the other choice fields (patterns §11.2); options with a `group` are listed under its heading.
	// Spread the Field's control props onto it.
	let {
		options,
		value,
		label,
		disabled = false,
		class: className,
		onchange,
		...control
	}: {
		options: readonly { value: string; label: string; group?: string }[];
		value: string;
		/** the accessible name of the button ("Kind") */
		label: string;
		disabled?: boolean;
		class?: string;
		onchange: (value: string) => void;
		id?: string;
		'aria-describedby'?: string;
		'aria-invalid'?: boolean;
	} = $props();

	let open = $state(false);
	const selected = $derived(options.find((o) => o.value === value) ?? null);
	const items = $derived<PickerItem[]>(
		options.map((o, id) => ({ id, label: o.label, group: o.group }))
	);
	const selectedId = $derived(options.findIndex((o) => o.value === value));

	function choose(id: number) {
		open = false;
		const next = options[id];
		if (next && next.value !== value) onchange(next.value);
	}
</script>

<Popover.Root bind:open>
	<Popover.Trigger
		{...control}
		aria-label={label}
		aria-invalid={control['aria-invalid'] || undefined}
		{disabled}
		data-slot="choice-select"
		class={cn(
			'flex h-8 w-full min-w-0 items-center justify-between gap-2 rounded-lg border border-input bg-transparent px-2.5 text-left text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive dark:bg-input/30',
			className
		)}
	>
		<span class="truncate">{selected?.label ?? ''}</span>
		<ChevronsUpDownIcon
			size={14}
			strokeWidth={1.75}
			class="shrink-0 text-muted-foreground"
			aria-hidden="true"
		/>
	</Popover.Trigger>
	<Popover.Content align="start" class="w-64 gap-0 p-1" aria-label={label}>
		<Picker
			{items}
			{selectedId}
			label={`${label} choices`}
			findLabel={`Search ${label.toLowerCase()}`}
			placeholder="Find…"
			onselect={choose}
		/>
	</Popover.Content>
</Popover.Root>
