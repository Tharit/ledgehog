<script lang="ts">
	import type { CategoriesStore } from '#lib/categories/store.svelte.js';
	import { CATEGORY_KINDS, visibleRows, type CategoryKind } from '#lib/categories/tree.js';
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

{#each CATEGORY_KINDS as kind (kind)}
	{@const rows = visibleRows(store.tree[kind], store.collapsed)}
	<section aria-labelledby={`category-root-${kind}`} data-kind={kind}>
		<h3 id={`category-root-${kind}`} class="mb-1 text-base font-semibold">{HEADINGS[kind]}</h3>
		{#if rows.length === 0}
			<p class="py-2 text-sm text-muted-foreground">No {kind} categories yet.</p>
		{:else}
			<ul aria-label={`${HEADINGS[kind]} categories`}>
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
			</ul>
		{/if}
	</section>
{/each}
