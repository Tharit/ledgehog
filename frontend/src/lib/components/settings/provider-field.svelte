<script lang="ts">
	import ChevronsUpDownIcon from '@lucide/svelte/icons/chevrons-up-down';
	import Picker, { type PickerItem } from '#lib/components/common/picker.svelte';
	import * as Popover from '#lib/components/ui/popover/index.js';

	// A payee's document provider, typed or picked like a tag (patterns §11.2): the known providers
	// are suggested, any other value is accepted as typed, and nothing is created (spec §3.6). The
	// value is trimmed by the caller; empty means none. Spread the Field's control props onto it.
	let {
		value,
		known,
		label,
		disabled = false,
		onchange,
		...control
	}: {
		value: string;
		/** the providers the registered importers know */
		known: readonly string[];
		/** the accessible name of the button ("Document provider") */
		label: string;
		disabled?: boolean;
		onchange: (value: string) => void;
		id?: string;
		'aria-describedby'?: string;
		'aria-invalid'?: boolean;
	} = $props();

	const NONE = 'No provider';
	let open = $state(false);
	// the value the payee holds stays listed even when no importer knows it
	const providers = $derived(
		[...new Set([...known, ...(value.trim() !== '' ? [value.trim()] : [])])].sort()
	);
	const items = $derived<PickerItem[]>([
		{ id: 0, label: NONE },
		...providers.map((p, i) => ({ id: i + 1, label: p }))
	]);
	const selectedId = $derived(Math.max(0, providers.indexOf(value.trim()) + 1));

	function choose(id: number) {
		open = false;
		onchange(id === 0 ? '' : (providers[id - 1] ?? ''));
	}

	function use(name: string) {
		open = false;
		onchange(name.trim());
	}
</script>

<Popover.Root bind:open>
	<Popover.Trigger
		{...control}
		aria-label={label}
		aria-invalid={control['aria-invalid'] || undefined}
		{disabled}
		data-slot="provider-field"
		class="flex h-8 w-full min-w-0 items-center justify-between gap-2 rounded-lg border border-input bg-transparent px-2.5 text-left text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive dark:bg-input/30"
	>
		<span class="truncate">{value.trim() === '' ? NONE : value.trim()}</span>
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
			placeholder="Find or type…"
			oncreate={use}
			createLabel={(name) => `Use “${name}”`}
			onselect={choose}
		/>
	</Popover.Content>
</Popover.Root>
