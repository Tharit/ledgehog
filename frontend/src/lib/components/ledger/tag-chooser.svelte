<script lang="ts">
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import * as Command from '#lib/components/ui/command/index.js';
	import { resolveTag } from '#lib/theme/resolve.js';
	import type { Tag } from '#lib/types/domain.js';

	// A searchable list of tags: colour dot, name, a check on the ones in `checked`. Typing a name
	// no tag has offers to create it. `↑` `↓` move, `Enter` chooses; what choosing does is the
	// caller's (toggle on a row, pick for "Tag all").
	let {
		tags,
		checked = new Set<number>(),
		busy = false,
		onselect,
		oncreate
	}: {
		tags: readonly Tag[];
		checked?: ReadonlySet<number>;
		/** a write is under way: choosing does nothing meanwhile */
		busy?: boolean;
		onselect: (tag: Tag) => void;
		oncreate: (name: string) => void;
	} = $props();

	let query = $state('');
	const needle = $derived(query.trim().toLowerCase());
	const sorted = $derived([...tags].sort((a, b) => a.name.localeCompare(b.name)));
	const shown = $derived(
		needle === '' ? sorted : sorted.filter((tag) => tag.name.toLowerCase().includes(needle))
	);
	// a name that is taken is chosen, not created (the API refuses duplicates)
	const creatable = $derived(needle !== '' && !tags.some((t) => t.name.toLowerCase() === needle));

	function choose(tag: Tag) {
		if (!busy) onselect(tag);
	}

	function create() {
		if (busy) return;
		const name = query.trim();
		query = '';
		oncreate(name);
	}
</script>

<Command.Root shouldFilter={false} aria-busy={busy}>
	<Command.Input placeholder="Find or create a tag…" aria-label="Search tags" bind:value={query} />
	<Command.List aria-label="Tags">
		{#each shown as tag (tag.id)}
			<Command.Item
				value={`tag-${tag.id}`}
				data-checked={checked.has(tag.id)}
				onSelect={() => choose(tag)}
			>
				<AccountDot name={tag.name} color={resolveTag(tag).color} />
				{#if checked.has(tag.id)}<span class="sr-only">(tagged)</span>{/if}
			</Command.Item>
		{/each}
		{#if creatable}
			<Command.Item value="create-new-tag" onSelect={create}>
				Create tag "{query.trim()}"
			</Command.Item>
		{/if}
		{#if shown.length === 0 && !creatable}
			<p class="px-2 py-6 text-center text-sm text-muted-foreground">
				No tags yet. Type a name to create one.
			</p>
		{/if}
	</Command.List>
</Command.Root>
