<script lang="ts">
	import ChevronsUpDownIcon from '@lucide/svelte/icons/chevrons-up-down';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import Picker, { type PickerItem } from '#lib/components/common/picker.svelte';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import type { Account } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';

	// One account chosen from a searchable list: the shared picker in a popover, the same trigger as
	// the other choice fields. Spread the Field's control props onto it.
	let {
		accounts,
		value = $bindable(null),
		label,
		disabled = false,
		onchange,
		...control
	}: {
		accounts: readonly Account[];
		value?: number | null;
		/** the accessible name of the button ("Account") */
		label: string;
		disabled?: boolean;
		onchange?: (id: number) => void;
		id?: string;
		'aria-describedby'?: string;
		'aria-invalid'?: boolean;
	} = $props();

	let open = $state(false);
	const selected = $derived(accounts.find((a) => a.id === value) ?? null);
	const items = $derived<PickerItem[]>(
		accounts.map((a) => ({ id: a.id, label: a.name, ...resolveAccount(a) }))
	);

	function choose(id: number) {
		value = id;
		onchange?.(id);
		open = false;
	}
</script>

<Popover.Root bind:open>
	<Popover.Trigger
		{...control}
		aria-label={label}
		aria-invalid={control['aria-invalid'] || undefined}
		{disabled}
		data-slot="account-select"
		class={cn(
			'flex h-8 w-full min-w-0 items-center justify-between gap-2 rounded-lg border border-input bg-transparent px-2.5 text-left text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive dark:bg-input/30',
			selected === null && 'text-muted-foreground'
		)}
	>
		<span class="flex min-w-0 items-center gap-2">
			{#if selected}
				<DimensionIcon {...resolveAccount(selected)} />
				<span class="truncate">{selected.name}</span>
			{:else}
				<span>Choose an account…</span>
			{/if}
		</span>
		<ChevronsUpDownIcon
			size={14}
			strokeWidth={1.75}
			class="shrink-0 text-muted-foreground"
			aria-hidden="true"
		/>
	</Popover.Trigger>
	<Popover.Content align="start" class="w-80 gap-0 p-1" aria-label="Choose an account">
		<Picker
			{items}
			selectedId={value}
			label="Accounts"
			findLabel="Search account"
			placeholder="Find an account…"
			emptyText="No account yet."
			onselect={choose}
		/>
	</Popover.Content>
</Popover.Root>
