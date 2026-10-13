<script lang="ts">
	import { descendantIds, pickerOptions } from '#lib/categories/tree.js';
	import { categoryMergeSummary } from '#lib/categories/summary.js';
	import type { CategoriesStore } from '#lib/categories/store.svelte.js';
	import { resolveCategory } from '#lib/theme/resolve.js';
	import MergeDialog from './merge-dialog.svelte';
	import type { PickerItem } from '#lib/components/common/picker.svelte';

	// Merge a category into another of its kind (spec §3.5): its entries and rules are repointed,
	// its children move under the target, same-named children merge. The source and its own
	// descendants are not offered (merging into a descendant is refused); the server decides the rest.
	let { store }: { store: CategoriesStore } = $props();

	const source = $derived(
		store.merge.sourceId === null ? undefined : store.byId.get(store.merge.sourceId)
	);
	const items = $derived.by<PickerItem[]>(() => {
		if (!source) return [];
		const exclude = new Set([source.id, ...descendantIds(source.id, store.categories)]);
		return pickerOptions(store.categories, source.kind, { exclude }).map((option) => {
			const category = store.byId.get(option.id);
			const look = resolveCategory(category, store.byId);
			return { id: option.id, label: option.label, icon: look.icon, color: look.color };
		});
	});
</script>

<MergeDialog
	flow={store.merge}
	title={`Merge ${source?.name ?? 'category'} into…`}
	description="Its entries and rules move to the target and it is deleted. Nothing returns to review."
	{items}
	label="categories"
>
	{#snippet summary(out)}
		{@const text = categoryMergeSummary(out, store.byId)}
		<p class="font-medium">{text.headline}</p>
		<ul class="flex list-disc flex-col gap-0.5 pl-5" aria-label="Merges">
			{#each text.pairs as pair, i (i)}
				<li>{pair}</li>
			{/each}
		</ul>
		{#if text.moved.length > 0}
			<ul class="flex list-disc flex-col gap-0.5 pl-5" aria-label="Moved subcategories">
				{#each text.moved as line, i (i)}
					<li>{line}</li>
				{/each}
			</ul>
		{/if}
		<p>{text.totals}.</p>
		{#each text.notes as note (note)}
			<p class="text-muted-foreground">{note}</p>
		{/each}
	{/snippet}
</MergeDialog>
