<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import type { CategoriesStore } from '#lib/categories/store.svelte.js';
	import Card from '#lib/components/common/card.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import NoticeLine from '#lib/components/common/notice-line.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import type { Category } from '#lib/types/domain.js';
	import CategoryAddDialog from './category-add-dialog.svelte';
	import CategoryDeleteDialog from './category-delete-dialog.svelte';
	import CategoryMergeDialog from './category-merge-dialog.svelte';
	import CategoryMoveDialog from './category-move-dialog.svelte';
	import CategoryTree from './category-tree.svelte';

	// The categories screen (spec §3.5): the tree and everything done to it. Renaming, colouring,
	// ordering and moving write directly; adding is a form dialog; deleting and merging are
	// previewed first (patterns §6, §11). Nothing here knows what a category may do: the server
	// refuses, the screen says so.
	let { store }: { store: CategoriesStore } = $props();

	onMount(() => void store.load());

	// "Add category" (parent null) and "Add subcategory to …"; the parent stays while the dialog
	// closes so that its title does not change under the closing animation
	let addOpen = $state(false);
	let addParent = $state<Category | null>(null);

	function openAdd(parent: Category | null) {
		addParent = parent;
		addOpen = true;
	}

	// the new row is revealed (its parent is expanded by the store), marked briefly and focused
	let revealedId = $state<number | null>(null);
	let focusRevealed = $state(false);
	let revealTimer: ReturnType<typeof setTimeout> | undefined;

	function reveal(category: Category) {
		addOpen = false;
		revealedId = category.id;
		focusRevealed = false;
		clearTimeout(revealTimer);
		revealTimer = setTimeout(() => (revealedId = null), 2500);
	}
	onDestroy(() => clearTimeout(revealTimer));

	let moving = $state<Category | null>(null);
	let moveOpen = $state(false);

	function openMove(category: Category) {
		moving = category;
		moveOpen = true;
	}
</script>

<div class="flex flex-col gap-4">
	<PageHeader
		title="Categories"
		description="What money was spent on or earned from. Colour and icon of a top-level category carry down to the categories below it."
		actionLabel="Add category"
		onaction={() => openAdd(null)}
		actionDisabled={store.status !== 'ready'}
	/>

	<NoticeLine notice={store.notice} />

	{#if store.status === 'loading'}
		<Card
			variant="flush"
			aria-busy="true"
			aria-label="Loading categories"
			data-slot="categories-loading"
		>
			{#each [0, 1, 2, 3, 4] as i (i)}
				<div class="flex h-12 items-center gap-3 border-b border-border px-4 last:border-b-0">
					<div class="size-8 shrink-0 animate-pulse rounded-full bg-muted"></div>
					<div
						class="h-3 animate-pulse rounded bg-muted"
						style:width={`${30 + ((i * 17) % 30)}%`}
					></div>
				</div>
			{/each}
		</Card>
	{:else if store.status === 'error' && store.error}
		<ErrorState
			title="The categories could not be loaded"
			message={store.error.message}
			onretry={() => store.load()}
		/>
	{:else}
		{#if store.categories.length === 0}
			<EmptyState
				title="No categories yet"
				actionLabel="Add category"
				onaction={() => openAdd(null)}
			>
				Categories say what each entry is for, and rules need one to set. Add your first, choosing
				whether it counts as expense or income; subcategories are added from its row.
			</EmptyState>
		{/if}
		<CategoryTree {store} {revealedId} {focusRevealed} onaddchild={openAdd} onmoveto={openMove} />
	{/if}
</div>

<CategoryAddDialog
	{store}
	open={addOpen}
	parent={addParent}
	onclose={() => (addOpen = false)}
	onadded={reveal}
	onclosedafteradd={() => (focusRevealed = true)}
/>
<CategoryMoveDialog {store} category={moving} open={moveOpen} onclose={() => (moveOpen = false)} />
<CategoryMergeDialog {store} />
<CategoryDeleteDialog {store} />
