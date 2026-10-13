<script lang="ts">
	import type { CategoriesStore } from '#lib/categories/store.svelte.js';
	import { moveBlocked, pickerOptions } from '#lib/categories/tree.js';
	import ActionDialog from '#lib/components/common/action-dialog.svelte';
	import { describeFailure } from '#lib/dimensions/errors.js';
	import { resolveCategory } from '#lib/theme/resolve.js';
	import type { Category } from '#lib/types/domain.js';
	import Picker, { type PickerItem } from '#lib/components/common/picker.svelte';

	// "Move Food under…": a pick dialog (patterns §11.2), opened from a menu item. Choosing the
	// parent is the whole action and can be redone, so it writes at once and closes; a refusal
	// stays in the dialog. Only categories of the same kind are offered; the category itself, its
	// subcategories and its current parent are shown but cannot be chosen.
	let {
		store,
		category,
		open,
		onclose
	}: { store: CategoriesStore; category: Category | null; open: boolean; onclose: () => void } =
		$props();

	const TOP = 0;
	let failure = $state<string | null>(null);

	$effect(() => {
		if (open) failure = null;
	});

	const items = $derived.by<PickerItem[]>(() => {
		if (!category) return [];
		const disable = moveBlocked(category, store.categories);
		const kindName = category.kind === 'income' ? 'Income' : 'Expense';
		return [
			{
				id: TOP,
				label: `Top level of ${kindName}`,
				disabled: category.parent_id === null ? 'current level' : undefined
			},
			...pickerOptions(store.categories, category.kind, { disable }).map((option) => {
				const look = resolveCategory(store.byId.get(option.id), store.byId);
				return {
					id: option.id,
					label: option.label,
					disabled: option.disabled,
					icon: look.icon,
					color: look.color
				};
			})
		];
	});

	async function moveTo(parentId: number) {
		if (!category) return;
		const result = await store.reparent(category.id, parentId === TOP ? null : parentId);
		if (result.ok) onclose();
		else failure = describeFailure(result.failure, 'category');
	}
</script>

<ActionDialog
	{open}
	{onclose}
	title={`Move ${category?.name ?? ''} under…`}
	description="Only categories of the same kind are offered; it cannot go under itself or one of its subcategories."
	mode="pick"
	feedback={failure ? { kind: 'error', text: failure } : null}
>
	<Picker
		{items}
		label="new parents"
		placeholder="Find a category…"
		onselect={(id) => void moveTo(id)}
	/>
</ActionDialog>
