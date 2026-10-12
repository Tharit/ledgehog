<script lang="ts">
	import { categoryDeleteSummary } from '#lib/categories/summary.js';
	import type { CategoriesStore } from '#lib/categories/store.svelte.js';
	import DeleteDialog from './delete-dialog.svelte';

	// Delete a category (spec §3.5): only while nothing references it and it has no children. The
	// server's dry run says which; when it is held the dialog offers Merge instead.
	let { store }: { store: CategoriesStore } = $props();

	const name = $derived(
		store.remove.id === null ? 'category' : (store.byId.get(store.remove.id)?.name ?? 'category')
	);
</script>

<DeleteDialog
	flow={store.remove}
	title={`Delete ${name}?`}
	onmerge={() => {
		const id = store.remove.id;
		store.remove.close();
		if (id !== null) store.merge.start(id);
	}}
>
	{#snippet body(out)}
		{@const text = categoryDeleteSummary(out)}
		{#if text.deletable}
			<p>Nothing uses {out.category.name}: no entries, no rules and no subcategories.</p>
		{:else}
			<p>{text.reason}</p>
		{/if}
	{/snippet}
</DeleteDialog>
