<script lang="ts">
	import * as Popover from '#lib/components/ui/popover/index.js';
	import type { Tag } from '#lib/types/domain.js';
	import TagChooser from './tag-chooser.svelte';

	// `t` on a row: the tags of that one entry, in a popover anchored to the row. It has no
	// trigger: the list opens it and says which row it belongs to.
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
</script>

<Popover.Root bind:open>
	<Popover.Content
		customAnchor={anchor}
		align="start"
		aria-label="Tag this entry"
		class="w-72 gap-0 p-1"
		onCloseAutoFocus={onclosefocus}
	>
		<TagChooser {tags} {checked} {busy} {onselect} {oncreate} />
	</Popover.Content>
</Popover.Root>
