<script lang="ts">
	import PlusIcon from '@lucide/svelte/icons/plus';
	import Picker from '#lib/components/common/picker.svelte';
	import TagChip from '#lib/components/common/tag-chip.svelte';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { tagItems } from '#lib/ledger/tag-items.js';
	import { resolveTag } from '#lib/theme/resolve.js';

	// The tags of one entry under the draft: its chips, and a multi-choice picker (the shared one,
	// patterns §11.2) to put tags on or take them off. Choosing keeps the picker open; adding a tag
	// that does not exist yet creates it at once (the tag is no part of the draft) and puts it on
	// the entry. There is no clear X and nothing is proposed: tags are the user's alone.
	let {
		tagIds,
		lookups,
		busy = false,
		ontoggle,
		oncreate
	}: {
		/** the tags the entry will have */
		tagIds: readonly number[];
		lookups: Lookups;
		/** a tag is being created, or the commit is under way: choosing does nothing meanwhile */
		busy?: boolean;
		ontoggle: (tagId: number) => void;
		oncreate: (name: string) => void;
	} = $props();

	let open = $state(false);
	const tags = $derived(
		tagIds.flatMap((id) => {
			const tag = lookups.tags.get(id);
			return tag ? [tag] : [];
		})
	);
	const items = $derived(tagItems([...lookups.tags.values()]));
	const checked = $derived(new Set(tagIds));
</script>

<div class="flex flex-wrap items-center gap-1" data-slot="tag-field">
	{#each tags as tag (tag.id)}
		<TagChip name={tag.name} color={resolveTag(tag).color} />
	{/each}
	<Popover.Root bind:open>
		<Popover.Trigger
			aria-label="Tags"
			data-picker="tags"
			class="inline-flex h-5 shrink-0 items-center gap-1 rounded-sm border border-dashed border-input px-1.5 text-xs text-muted-foreground outline-none hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
		>
			<PlusIcon size={12} aria-hidden="true" />
			{#if tags.length === 0}<span>Add tag</span>{/if}
		</Popover.Trigger>
		<Popover.Content align="start" class="w-72 gap-0 p-1" aria-label="Tag this entry">
			<Picker
				{items}
				{checked}
				checkedLabel="tagged"
				{busy}
				label="Tags"
				findLabel="Search tags"
				placeholder="Find or add a tag…"
				emptyText="No tags yet. Type a name to add one."
				{oncreate}
				createLabel={(name) => `Add tag “${name}”`}
				onselect={ontoggle}
			/>
		</Popover.Content>
	</Popover.Root>
</div>
