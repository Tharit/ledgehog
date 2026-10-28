<script lang="ts">
	import PencilIcon from '@lucide/svelte/icons/pencil';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import type { CategoriesStore } from '#lib/categories/store.svelte.js';
	import { inheritHint } from '#lib/categories/look.js';
	import type { TreeRow } from '#lib/categories/tree.js';
	import InlineEdit from '#lib/components/common/inline-edit.svelte';
	import RowActions, { type RowAction } from '#lib/components/common/row-actions.svelte';
	import TreeToggle from '#lib/components/common/tree-toggle.svelte';
	import { describeFailure } from '#lib/dimensions/errors.js';
	import { CATEGORY_ICONS } from '#lib/theme/icon-sets.js';
	import { resolveCategory } from '#lib/theme/resolve.js';
	import { cn } from '#lib/utils.js';
	import LookPicker from './look-picker.svelte';

	// One category row of the tree (comfortable density, design §5): its look and name, where the
	// look comes from when it is not its own, and the actions (patterns §11.3): rename in place
	// and add a subcategory inline; reorder among siblings, move under another parent, merge and
	// delete in the `⋯` menu. The server decides what is allowed; its refusals are shown beside
	// the field they came from, or in the dialog the action opened.
	let {
		row,
		store,
		revealed = false,
		focus = false,
		onaddchild,
		onmoveto
	}: {
		row: TreeRow;
		store: CategoriesStore;
		/** just added: marked briefly */
		revealed?: boolean;
		/** just added and the dialog has closed: take focus */
		focus?: boolean;
		/** "Add subcategory": the manager opens its dialog for this category */
		onaddchild: () => void;
		/** "Move to…": the manager opens the picker for this category */
		onmoveto: () => void;
	} = $props();

	const category = $derived(row.category);
	const look = $derived(resolveCategory(category, store.byId));
	const hint = $derived(inheritHint(category, store.byId));

	let renaming = $state(false);
	let busy = $state(false);
	let body = $state<HTMLElement | null>(null);

	$effect(() => {
		if (!focus || !body) return;
		body.scrollIntoView({ block: 'nearest' });
		body.focus();
	});

	async function rename(name: string): Promise<string | null> {
		const result = await store.rename(category.id, name);
		return result.ok ? null : describeFailure(result.failure, 'category', name);
	}

	async function move(direction: 'up' | 'down') {
		busy = true;
		const result = await store.move(category.id, direction);
		busy = false;
		if (!result.ok) store.notify(describeFailure(result.failure, 'category'), true);
	}

	async function changeLook(patch: { icon?: string | null; color?: string | null }) {
		const result = await store.setLook(category.id, patch);
		if (!result.ok) store.notify(describeFailure(result.failure, 'category'), true);
	}

	const primary = $derived<RowAction[]>([
		{ verb: 'Rename', icon: PencilIcon, onselect: () => (renaming = true) },
		{
			verb: 'Add subcategory',
			label: `Add subcategory to ${category.name}`,
			icon: PlusIcon,
			onselect: onaddchild
		}
	]);
	const menu = $derived<RowAction[]>([
		{ verb: 'Move up', disabled: row.first || busy, onselect: () => void move('up') },
		{ verb: 'Move down', disabled: row.last || busy, onselect: () => void move('down') },
		{ verb: 'Move to…', onselect: onmoveto },
		{ verb: 'Merge…', onselect: () => store.merge.start(category.id) },
		{ verb: 'Delete…', destructive: true, onselect: () => void store.remove.start(category.id) }
	]);
</script>

<li
	class="border-b border-border last:border-b-0"
	data-slot="category-row"
	data-category-id={category.id}
	data-revealed={revealed || undefined}
>
	<div
		bind:this={body}
		tabindex="-1"
		class={cn(
			'group flex min-h-12 items-center gap-2 px-4 py-1 transition-colors duration-1000 outline-none focus-visible:ring-2 focus-visible:ring-ring',
			'rounded-[inherit]',
			revealed && 'bg-accent'
		)}
		style:padding-left={`${16 + row.depth * 24}px`}
	>
		<TreeToggle
			name={category.name}
			expanded={!row.collapsed}
			toggleable={row.hasChildren}
			ontoggle={() => store.toggle(category.id)}
		/>

		<LookPicker
			name={category.name}
			icon={category.icon}
			color={category.color}
			icons={CATEGORY_ICONS}
			shownIcon={look.icon}
			shownColor={look.color}
			clearLabel="Inherit"
			onchange={changeLook}
		/>

		<div class="flex min-w-0 flex-1 flex-col">
			{#if renaming}
				<InlineEdit
					value={category.name}
					label={`Name of ${category.name}`}
					onsave={rename}
					ondone={() => (renaming = false)}
					oncancel={() => (renaming = false)}
				/>
			{:else}
				<span class="truncate text-sm font-medium">{category.name}</span>
				{#if hint}
					<span class="truncate text-xs text-muted-foreground" data-slot="look-hint">{hint}</span>
				{/if}
			{/if}
		</div>

		<RowActions name={category.name} {primary} {menu} />
	</div>
</li>
