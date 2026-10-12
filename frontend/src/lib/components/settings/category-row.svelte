<script lang="ts">
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import ChevronUpIcon from '@lucide/svelte/icons/chevron-up';
	import CornerDownRightIcon from '@lucide/svelte/icons/corner-down-right';
	import GitMergeIcon from '@lucide/svelte/icons/git-merge';
	import PencilIcon from '@lucide/svelte/icons/pencil';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import Trash2Icon from '@lucide/svelte/icons/trash-2';
	import type { CategoriesStore } from '#lib/categories/store.svelte.js';
	import { inheritHint } from '#lib/categories/look.js';
	import type { TreeRow } from '#lib/categories/tree.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { describeFailure } from '#lib/dimensions/errors.js';
	import { CATEGORY_ICONS } from '#lib/theme/icon-sets.js';
	import { resolveCategory } from '#lib/theme/resolve.js';
	import LookPicker from './look-picker.svelte';

	// One category row of the tree (comfortable density, design §5): its look and name, where the
	// look comes from when it is not its own, and the actions: reorder among siblings, rename in
	// place, add a subcategory, move under another parent, merge and delete. The server decides
	// what is allowed; its refusals are shown beside the field they came from.
	let {
		row,
		store,
		onmoveto
	}: {
		row: TreeRow;
		store: CategoriesStore;
		/** "Move to…": the manager opens the picker for this category */
		onmoveto: () => void;
	} = $props();

	const category = $derived(row.category);
	const look = $derived(resolveCategory(category, store.byId));
	const hint = $derived(inheritHint(category, store.byId));

	let renaming = $state(false);
	let nameDraft = $state('');
	let nameError = $state<string | null>(null);
	let adding = $state(false);
	let childName = $state('');
	let childError = $state<string | null>(null);
	let busy = $state(false);
	let renameInput = $state<HTMLInputElement | null>(null);
	let childInput = $state<HTMLInputElement | null>(null);

	$effect(() => {
		if (renaming) renameInput?.focus();
	});
	$effect(() => {
		if (adding) childInput?.focus();
	});

	function startRename() {
		nameDraft = category.name;
		nameError = null;
		renaming = true;
	}

	async function saveRename() {
		const name = nameDraft.trim();
		if (name === '' || name === category.name) {
			renaming = false;
			return;
		}
		busy = true;
		const result = await store.rename(category.id, name);
		busy = false;
		if (result.ok) renaming = false;
		else nameError = describeFailure(result.failure, 'category', name);
	}

	async function addChild() {
		const name = childName.trim();
		if (name === '') return;
		busy = true;
		const result = await store.create(name, { parentId: category.id });
		busy = false;
		if (result.ok) {
			adding = false;
			childName = '';
			childError = null;
		} else {
			childError = describeFailure(result.failure, 'category', name);
		}
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

	function key(event: KeyboardEvent, save: () => void, cancel: () => void) {
		if (event.key === 'Enter') {
			event.preventDefault();
			save();
		} else if (event.key === 'Escape') {
			event.preventDefault();
			event.stopPropagation();
			cancel();
		}
	}
</script>

<li data-slot="category-row" data-category-id={category.id}>
	<div
		class="flex min-h-12 items-center gap-2 border-b border-border py-1"
		style:padding-left={`${row.depth * 24}px`}
	>
		{#if row.hasChildren}
			<Button
				variant="ghost"
				size="icon-xs"
				aria-label={row.collapsed ? `Expand ${category.name}` : `Collapse ${category.name}`}
				aria-expanded={!row.collapsed}
				onclick={() => store.toggle(category.id)}
			>
				{#if row.collapsed}<ChevronRightIcon aria-hidden="true" />{:else}<ChevronDownIcon
						aria-hidden="true"
					/>{/if}
			</Button>
		{:else}
			<span class="size-6 shrink-0" aria-hidden="true"></span>
		{/if}

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
				<Input
					bind:ref={renameInput}
					bind:value={nameDraft}
					aria-label={`Name of ${category.name}`}
					aria-invalid={nameError !== null}
					disabled={busy}
					onkeydown={(event) => key(event, saveRename, () => (renaming = false))}
					onblur={() => {
						if (!busy) renaming = false;
					}}
				/>
				{#if nameError}
					<span role="alert" class="text-xs text-destructive">{nameError}</span>
				{/if}
			{:else}
				<span class="truncate text-sm font-medium">{category.name}</span>
				{#if hint}
					<span class="truncate text-xs text-muted-foreground" data-slot="look-hint">{hint}</span>
				{/if}
			{/if}
		</div>

		<div class="flex shrink-0 items-center gap-0.5 text-muted-foreground">
			<Button
				variant="ghost"
				size="icon-xs"
				aria-label={`Move ${category.name} up`}
				title="Move up"
				disabled={row.first || busy}
				onclick={() => move('up')}
			>
				<ChevronUpIcon aria-hidden="true" />
			</Button>
			<Button
				variant="ghost"
				size="icon-xs"
				aria-label={`Move ${category.name} down`}
				title="Move down"
				disabled={row.last || busy}
				onclick={() => move('down')}
			>
				<ChevronDownIcon aria-hidden="true" />
			</Button>
			<Button
				variant="ghost"
				size="icon-xs"
				aria-label={`Rename ${category.name}`}
				title="Rename"
				onclick={startRename}
			>
				<PencilIcon aria-hidden="true" />
			</Button>
			<Button
				variant="ghost"
				size="icon-xs"
				aria-label={`Add a subcategory to ${category.name}`}
				title="Add subcategory"
				onclick={() => {
					childError = null;
					adding = true;
				}}
			>
				<PlusIcon aria-hidden="true" />
			</Button>
			<Button
				variant="ghost"
				size="icon-xs"
				aria-label={`Move ${category.name} under another category`}
				title="Move to…"
				onclick={onmoveto}
			>
				<CornerDownRightIcon aria-hidden="true" />
			</Button>
			<Button
				variant="ghost"
				size="icon-xs"
				aria-label={`Merge ${category.name} into another category`}
				title="Merge…"
				onclick={() => store.merge.start(category.id)}
			>
				<GitMergeIcon aria-hidden="true" />
			</Button>
			<Button
				variant="ghost"
				size="icon-xs"
				aria-label={`Delete ${category.name}`}
				title="Delete…"
				onclick={() => void store.remove.start(category.id)}
			>
				<Trash2Icon aria-hidden="true" />
			</Button>
		</div>
	</div>

	{#if adding}
		<form
			class="flex items-start gap-2 border-b border-border py-2"
			style:padding-left={`${(row.depth + 1) * 24 + 32}px`}
			onsubmit={(event) => {
				event.preventDefault();
				void addChild();
			}}
		>
			<div class="flex flex-1 flex-col gap-1">
				<Input
					bind:ref={childInput}
					bind:value={childName}
					placeholder={`Subcategory of ${category.name}`}
					aria-label={`Name of the new subcategory of ${category.name}`}
					aria-invalid={childError !== null}
					disabled={busy}
					onkeydown={(event) => {
						if (event.key === 'Escape') {
							event.stopPropagation();
							adding = false;
						}
					}}
				/>
				{#if childError}
					<span role="alert" class="text-xs text-destructive">{childError}</span>
				{/if}
			</div>
			<Button type="submit" size="sm" disabled={busy || childName.trim() === ''}>Add</Button>
			<Button variant="ghost" size="sm" onclick={() => (adding = false)}>Cancel</Button>
		</form>
	{/if}
</li>
