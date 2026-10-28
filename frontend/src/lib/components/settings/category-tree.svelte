<script lang="ts">
	import type { CategoriesStore } from '#lib/categories/store.svelte.js';
	import { CATEGORY_KINDS, visibleRows, type CategoryKind } from '#lib/categories/tree.js';
	import Card from '#lib/components/common/card.svelte';
	import type { Category } from '#lib/types/domain.js';
	import CategoryRow from './category-row.svelte';

	// The tree (spec §3.5): the two roots, Income and Expense, are the kinds themselves and so
	// headings, not rows; the categories below them are indented and fold away.
	let {
		store,
		revealedId = null,
		focusRevealed = false,
		onaddchild,
		onmoveto
	}: {
		store: CategoriesStore;
		/** the category just added: its row is marked and focused */
		revealedId?: number | null;
		/** the dialog that added it has closed: the revealed row takes focus */
		focusRevealed?: boolean;
		onaddchild: (category: Category) => void;
		onmoveto: (category: Category) => void;
	} = $props();

	const HEADINGS: Record<CategoryKind, string> = { expense: 'Expense', income: 'Income' };
</script>

<div class="flex flex-col gap-6">
	{#each CATEGORY_KINDS as kind (kind)}
		{@const rows = visibleRows(store.tree[kind], store.collapsed)}
		<section aria-labelledby={`category-root-${kind}`} class="flex flex-col gap-1" data-kind={kind}>
			<h3 id={`category-root-${kind}`} class="text-base font-semibold">{HEADINGS[kind]}</h3>
			{#if rows.length === 0}
				<Card variant="flush">
					<p class="px-4 py-3 text-sm text-muted-foreground">No {kind} categories yet.</p>
				</Card>
			{:else}
				<Card variant="flush" element="ul" aria-label={`${HEADINGS[kind]} categories`}>
					{#each rows as row (row.category.id)}
						<CategoryRow
							{row}
							{store}
							revealed={row.category.id === revealedId}
							focus={focusRevealed && row.category.id === revealedId}
							onaddchild={() => onaddchild(row.category)}
							onmoveto={() => onmoveto(row.category)}
						/>
					{/each}
				</Card>
			{/if}
		</section>
	{/each}
</div>
