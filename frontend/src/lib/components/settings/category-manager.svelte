<script lang="ts">
	import { onMount } from 'svelte';
	import type { CategoriesStore } from '#lib/categories/store.svelte.js';
	import { moveBlocked, pickerOptions, type CategoryKind } from '#lib/categories/tree.js';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { describeFailure } from '#lib/dimensions/errors.js';
	import { resolveCategory } from '#lib/theme/resolve.js';
	import type { Category } from '#lib/types/domain.js';
	import CategoryDeleteDialog from './category-delete-dialog.svelte';
	import CategoryMergeDialog from './category-merge-dialog.svelte';
	import CategoryTree from './category-tree.svelte';
	import EntityPicker, { type PickerItem } from './entity-picker.svelte';

	// The categories screen (spec §3.5): the tree and everything done to it. Creating, renaming,
	// colouring, ordering and moving write directly; deleting and merging are previewed first
	// (patterns §6). Nothing here knows what a category may do: the server refuses, the screen says so.
	let { store }: { store: CategoriesStore } = $props();

	onMount(() => void store.load());

	// the new top-level category
	let adding = $state(false);
	let name = $state('');
	let kind = $state<CategoryKind>('expense');
	let addError = $state<string | null>(null);
	let busy = $state(false);

	async function add() {
		const trimmed = name.trim();
		if (trimmed === '') return;
		busy = true;
		const result = await store.create(trimmed, { kind });
		busy = false;
		if (result.ok) {
			adding = false;
			name = '';
			addError = null;
		} else {
			addError = describeFailure(result.failure, 'category', trimmed);
		}
	}

	// "Move to…": the parent to put a category under, of its own kind
	const TOP = 0;
	let moving = $state<Category | null>(null);
	let moveError = $state<string | null>(null);

	const moveItems = $derived.by<PickerItem[]>(() => {
		const category = moving;
		if (!category) return [];
		const disable = moveBlocked(category, store.categories);
		const kindName = category.kind === 'income' ? 'Income' : 'Expense';
		return [
			{
				id: TOP,
				label: `Top level of ${kindName}`,
				disabled: category.parent_id === null ? 'current level' : undefined
			},
			...pickerOptions(store.categories, category.kind, { disable }).map((option) => ({
				id: option.id,
				label: option.label,
				disabled: option.disabled,
				icon: resolveCategory(store.byId.get(option.id), store.byId).icon,
				color: resolveCategory(store.byId.get(option.id), store.byId).color
			}))
		];
	});

	function openMove(category: Category) {
		moveError = null;
		moving = category;
	}

	async function moveTo(parentId: number) {
		if (!moving) return;
		const result = await store.reparent(moving.id, parentId === TOP ? null : parentId);
		if (result.ok) {
			moving = null;
			moveError = null;
		} else {
			moveError = describeFailure(result.failure, 'category');
		}
	}
</script>

<div class="flex flex-col gap-4">
	<div class="flex items-start justify-between gap-4">
		<div class="flex flex-col gap-1">
			<h2 class="text-base font-semibold">Categories</h2>
			<p class="max-w-prose text-sm text-muted-foreground">
				What money was spent on or earned from. Colour and icon of a top-level category carry down
				to the categories below it.
			</p>
		</div>
		<Button
			size="sm"
			disabled={store.status !== 'ready'}
			onclick={() => {
				addError = null;
				adding = !adding;
			}}
		>
			Add category
		</Button>
	</div>

	{#if adding}
		<form
			class="flex flex-wrap items-start gap-2 rounded-lg border border-border bg-card p-3"
			aria-label="New category"
			onsubmit={(event) => {
				event.preventDefault();
				void add();
			}}
		>
			<div class="flex flex-col gap-1">
				<Input
					bind:value={name}
					placeholder="Category name"
					aria-label="Name of the new category"
					aria-invalid={addError !== null}
					disabled={busy}
					class="w-64"
				/>
				{#if addError}
					<span role="alert" class="text-xs text-destructive">{addError}</span>
				{/if}
			</div>
			<fieldset class="flex h-8 items-center gap-3 text-sm">
				<legend class="sr-only">Kind</legend>
				<label class="flex items-center gap-1.5">
					<input type="radio" class="accent-primary" bind:group={kind} value="expense" />
					Expense
				</label>
				<label class="flex items-center gap-1.5">
					<input type="radio" class="accent-primary" bind:group={kind} value="income" />
					Income
				</label>
			</fieldset>
			<Button type="submit" size="sm" disabled={busy || name.trim() === ''}>Create</Button>
			<Button variant="ghost" size="sm" onclick={() => (adding = false)}>Cancel</Button>
			<p class="basis-full text-xs text-muted-foreground">
				The kind cannot be changed later; subcategories take their parent's.
			</p>
		</form>
	{/if}

	<div class="flex min-h-5 flex-col gap-1">
		{#if store.notice}
			<Notice role={store.notice.error ? 'alert' : 'status'}>{store.notice.text}</Notice>
		{/if}
	</div>

	{#if store.status === 'loading'}
		<p class="text-sm text-muted-foreground" aria-busy="true">Loading categories…</p>
	{:else if store.status === 'error' && store.error}
		<ErrorState
			title="The categories could not be loaded"
			message={store.error.message}
			onretry={() => store.load()}
		/>
	{:else}
		{#if store.categories.length === 0}
			<div class="rounded-lg border border-dashed border-border p-6 text-sm" data-slot="empty">
				<p class="font-medium">No categories yet</p>
				<p class="mt-1 max-w-prose text-muted-foreground">
					Categories say what each entry is for, and rules need one to set. Add your first with “Add
					category”, choosing whether it counts as expense or income; subcategories are added from
					its row.
				</p>
			</div>
		{/if}
		<CategoryTree {store} onmoveto={openMove} />
	{/if}
</div>

<Dialog.Root
	open={moving !== null}
	onOpenChange={(next) => {
		if (!next) moving = null;
	}}
>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>Move {moving?.name ?? ''} under…</Dialog.Title>
			<Dialog.Description>
				Only categories of the same kind are offered; it cannot go under itself or one of its
				subcategories.
			</Dialog.Description>
		</Dialog.Header>
		<EntityPicker
			items={moveItems}
			label="new parents"
			placeholder="Find a category…"
			onselect={(id) => void moveTo(id)}
		/>
		{#if moveError}
			<p role="alert" class="text-sm text-destructive">{moveError}</p>
		{/if}
		<Dialog.Footer>
			<Button variant="outline" onclick={() => (moving = null)}>Cancel</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>

<CategoryMergeDialog {store} />
<CategoryDeleteDialog {store} />
