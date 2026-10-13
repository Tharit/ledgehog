<script lang="ts">
	import Picker from '#lib/components/common/picker.svelte';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import { tagItems } from '#lib/ledger/tag-items.js';
	import type { Tag } from '#lib/types/domain.js';

	// `t` on a row, or a click on its tags cell: the tags of that one entry, in a popover anchored
	// to the row. It has no trigger of its own: the list opens it and says which row it belongs to.
	let {
		open = $bindable(false),
		anchor = null,
		tags,
		checked,
		busy = false,
		onselect,
		oncreate,
		onclosefocus
	}: {
		open?: boolean;
		/** the row the popover hangs from */
		anchor?: HTMLElement | null;
		tags: readonly Tag[];
		/** the tags the entry carries now */
		checked: ReadonlySet<number>;
		busy?: boolean;
		onselect: (tag: Tag) => void;
		oncreate: (name: string) => void;
		/** the popover closed: where the keyboard goes back to */
		onclosefocus?: (event: Event) => void;
	} = $props();

	const items = $derived(tagItems(tags));
</script>

<Popover.Root bind:open>
	<Popover.Content
		customAnchor={anchor}
		align="start"
		aria-label="Tag this entry"
		class="w-72 gap-0 p-1"
		onCloseAutoFocus={onclosefocus}
	>
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
			onselect={(id) => {
				const tag = tags.find((t) => t.id === id);
				if (tag) onselect(tag);
			}}
		/>
	</Popover.Content>
</Popover.Root>
