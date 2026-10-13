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
		/** a colour dot and the name instead of an icon tile (tags) */
		dot?: boolean;
	};
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import * as Command from '#lib/components/ui/command/index.js';

	// The one list to choose from (patterns §11.2 "Popover choice" / "Pick dialog"): a find box,
	// items, and one line when there is nothing to show. `↑` `↓` move, `Enter` or a click chooses;
	// what choosing does is the caller's. An item that cannot be chosen is shown with its reason.
	// Only where the context allows it (tags) it offers `Add tag “x”` for a name nothing has yet:
	// pass `oncreate`. `row` draws an item differently from the default icon and label.
	let {
		items,
		label,
		findLabel,
		placeholder = 'Find…',
		emptyText = 'Nothing to choose from.',
		error = null,
		selectedId = null,
		checked,
		checkedLabel = 'selected',
		busy = false,
		oncreate,
		createLabel = (name: string) => `Add “${name}”`,
		row,
		onselect
	}: {
		items: readonly PickerItem[];
		/** the list's accessible name */
		label: string;
		/** the find box's accessible name; default "Search <label>" */
		findLabel?: string;
		/** an imperative ending in "…" ("Find a category…") */
		placeholder?: string;
		/** one line, when there is nothing at all to choose from */
		emptyText?: string;
		/** the items could not be had: this line replaces the list */
		error?: string | null;
		selectedId?: number | null;
		/** items shown with a check (the tags an entry carries) */
		checked?: ReadonlySet<number>;
		/** what a screen reader hears for a checked item */
		checkedLabel?: string;
		/** a write is under way: choosing does nothing meanwhile */
		busy?: boolean;
		/** offers to add the typed name when no item has it; absent where adding is not allowed here */
		oncreate?: (name: string) => void;
		createLabel?: (name: string) => string;
		row?: Snippet<[PickerItem]>;
		onselect: (id: number) => void;
	} = $props();

	let query = $state('');
	const needle = $derived(query.trim().toLowerCase());
	const shown = $derived(
		needle === '' ? items : items.filter((item) => item.label.toLowerCase().includes(needle))
	);
	// a name that is taken is chosen, not added (the API refuses duplicates)
	const creatable = $derived(
		oncreate !== undefined && needle !== '' && !items.some((i) => i.label.toLowerCase() === needle)
	);

	function choose(id: number) {
		if (!busy) onselect(id);
	}

	function create() {
		if (busy || !oncreate) return;
		const name = query.trim();
		query = '';
		oncreate(name);
	}
</script>

<Command.Root shouldFilter={false} aria-busy={busy}>
	<Command.Input {placeholder} aria-label={findLabel ?? `Search ${label}`} bind:value={query} />
	<Command.List aria-label={label} class="max-h-64">
		{#if error}
			<p role="alert" class="px-2 py-6 text-center text-sm text-destructive">{error}</p>
		{:else}
			{#each shown as item (item.id)}
				<Command.Item
					value={`item-${item.id}`}
					disabled={item.disabled !== undefined}
					data-checked={checked ? checked.has(item.id) : item.id === selectedId}
					onSelect={() => choose(item.id)}
				>
					{#if row}
						{@render row(item)}
					{:else if item.dot}
						<AccountDot name={item.label} color={item.color} />
					{:else}
						{#if item.icon !== undefined || item.initial !== undefined}
							<DimensionIcon icon={item.icon} color={item.color} initial={item.initial} />
						{/if}
						<span class="truncate">{item.label}</span>
					{/if}
					{#if checked?.has(item.id)}<span class="sr-only">({checkedLabel})</span>{/if}
					{#if item.disabled}
						<span class="ml-auto shrink-0 text-xs text-muted-foreground">{item.disabled}</span>
					{/if}
				</Command.Item>
			{/each}
			{#if creatable}
				<Command.Item value="add-new" onSelect={create}>{createLabel(query.trim())}</Command.Item>
			{/if}
			{#if shown.length === 0 && !creatable}
				<p class="px-2 py-6 text-center text-sm text-muted-foreground">
					{items.length === 0 ? emptyText : 'No match.'}
				</p>
			{/if}
		{/if}
	</Command.List>
</Command.Root>
