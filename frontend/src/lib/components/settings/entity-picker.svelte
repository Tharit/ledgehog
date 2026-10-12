<script lang="ts" module>
	export type PickerItem = {
		id: number;
		/** searchable; for a category its path */
		label: string;
		/** why it cannot be chosen; absent when it can */
		disabled?: string;
		icon?: string | null;
		color?: string | null;
		/** stands in for the icon (a payee without one) */
		initial?: string;
	};
</script>

<script lang="ts">
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import * as Command from '#lib/components/ui/command/index.js';

	// A searchable list to pick a category or payee from (a merge target, a new parent). `↑` `↓`
	// move, `Enter` or a click chooses; an item that cannot be chosen is shown with its reason.
	let {
		items,
		label,
		placeholder = 'Search…',
		emptyText = 'Nothing to choose from.',
		selectedId = null,
		onselect
	}: {
		items: readonly PickerItem[];
		/** the list's accessible name */
		label: string;
		placeholder?: string;
		emptyText?: string;
		selectedId?: number | null;
		onselect: (id: number) => void;
	} = $props();

	let query = $state('');
	const needle = $derived(query.trim().toLowerCase());
	const shown = $derived(
		needle === '' ? items : items.filter((item) => item.label.toLowerCase().includes(needle))
	);
</script>

<Command.Root shouldFilter={false}>
	<Command.Input {placeholder} aria-label={`Search ${label}`} bind:value={query} />
	<Command.List aria-label={label} class="max-h-64">
		{#each shown as item (item.id)}
			<Command.Item
				value={`item-${item.id}`}
				disabled={item.disabled !== undefined}
				data-checked={item.id === selectedId}
				onSelect={() => onselect(item.id)}
			>
				{#if item.icon !== undefined || item.initial !== undefined}
					<DimensionIcon icon={item.icon} color={item.color} initial={item.initial} />
				{/if}
				<span class="truncate">{item.label}</span>
				{#if item.disabled}
					<span class="ml-auto shrink-0 text-xs text-muted-foreground">{item.disabled}</span>
				{/if}
			</Command.Item>
		{/each}
		{#if shown.length === 0}
			<p class="px-2 py-6 text-center text-sm text-muted-foreground">
				{items.length === 0 ? emptyText : 'No match.'}
			</p>
		{/if}
	</Command.List>
</Command.Root>
