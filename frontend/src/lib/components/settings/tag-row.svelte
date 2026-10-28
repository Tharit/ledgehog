<script lang="ts">
	import PencilIcon from '@lucide/svelte/icons/pencil';
	import InlineEdit from '#lib/components/common/inline-edit.svelte';
	import RowActions, { type RowAction } from '#lib/components/common/row-actions.svelte';
	import { describeFailure } from '#lib/dimensions/errors.js';
	import { entriesLabel, tagSpan } from '#lib/tags/summary.js';
	import type { TagsStore } from '#lib/tags/store.svelte.js';
	import { resolveDimensionColor } from '#lib/theme/dimensions.js';
	import type { Tag } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';
	import LookPicker from './look-picker.svelte';

	// One tag (comfortable density, design §5): its colour (the swatch opens the colour choices),
	// name, how many entries carry it and the span they cover. Rename is in place; Delete… is in
	// the `⋯` menu and opens the manager's decision dialog (patterns §11.3).
	let {
		tag,
		store,
		revealed = false,
		focus = false,
		ondelete
	}: {
		tag: Tag;
		store: TagsStore;
		/** just added: marked briefly */
		revealed?: boolean;
		/** just added and the dialog has closed: take focus */
		focus?: boolean;
		ondelete: () => void;
	} = $props();

	let renaming = $state(false);
	let body = $state<HTMLElement | null>(null);

	$effect(() => {
		if (!focus || !body) return;
		body.scrollIntoView({ block: 'nearest' });
		body.focus();
	});

	async function rename(name: string): Promise<string | null> {
		const result = await store.update(tag.id, { name });
		return result.ok ? null : describeFailure(result.failure, 'tag', name);
	}

	async function changeColor(patch: { icon?: string | null; color?: string | null }) {
		if (patch.color === undefined) return;
		const result = await store.update(tag.id, { color: patch.color });
		if (!result.ok) store.notify(describeFailure(result.failure, 'tag'), true);
	}

	const primary = $derived<RowAction[]>([
		{ verb: 'Rename', icon: PencilIcon, onselect: () => (renaming = true) }
	]);
	const menu = $derived<RowAction[]>([{ verb: 'Delete…', destructive: true, onselect: ondelete }]);
</script>

<li
	class="border-b border-border last:border-b-0"
	data-slot="tag-row"
	data-tag-id={tag.id}
	data-revealed={revealed || undefined}
>
	<div
		bind:this={body}
		tabindex="-1"
		class={cn(
			'group flex min-h-12 items-center gap-3 px-4 py-1 transition-colors duration-1000 outline-none focus-visible:ring-2 focus-visible:ring-ring',
			'rounded-[inherit]',
			revealed && 'bg-accent'
		)}
	>
		<LookPicker
			name={tag.name}
			icon={null}
			color={tag.color}
			shownColor={resolveDimensionColor(tag.color)}
			clearLabel="None"
			onchange={changeColor}
		/>

		<div class="flex min-w-0 flex-1 flex-col">
			{#if renaming}
				<InlineEdit
					value={tag.name}
					label={`Name of ${tag.name}`}
					onsave={rename}
					ondone={() => (renaming = false)}
					oncancel={() => (renaming = false)}
				/>
			{:else}
				<span class="truncate text-sm font-medium">{tag.name}</span>
				<span class="truncate text-xs text-muted-foreground">
					<span data-slot="entry-count">{entriesLabel(tag.entry_count)}</span>
					{#if tag.entry_count > 0}· <span data-slot="span">{tagSpan(tag)}</span>{/if}
				</span>
			{/if}
		</div>

		<RowActions name={tag.name} {primary} {menu} />
	</div>
</li>
