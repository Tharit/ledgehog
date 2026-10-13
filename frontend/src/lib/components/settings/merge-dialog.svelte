<script lang="ts" generics="Out extends { entry_count: number }">
	import type { Snippet } from 'svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import type { MergeFlow } from '#lib/dimensions/flows.svelte.js';
	import EntityPicker, { type PickerItem } from './entity-picker.svelte';

	// The merge dialog both dimensions share, a decision dialog (spec §3.5, §3.6): choose the
	// target, read the server's dry run, merge explicitly. The consequence list is the caller's
	// `summary`; nothing is written until "Merge" is pressed, and the count the preview showed goes
	// with it. A moved count is a conflict (said plainly, then confirmed again), a refusal an error.
	let {
		flow,
		title,
		description,
		items,
		label,
		summary
	}: {
		flow: MergeFlow<Out>;
		title: string;
		description: string;
		/** the targets on offer (the source and what it cannot merge into already left out) */
		items: readonly PickerItem[];
		/** what the targets are: "categories", "payees" */
		label: string;
		/** the consequence list of a preview */
		summary: Snippet<[Out]>;
	} = $props();

	const merging = $derived(flow.status === 'merging');
	const target = $derived(items.find((item) => item.id === flow.targetId)?.label ?? '');
	const feedback = $derived<DialogFeedback | null>(
		flow.message
			? { kind: 'error', text: flow.message }
			: flow.moved
				? { kind: 'conflict', text: flow.moved }
				: null
	);
</script>

<ActionDialog
	open={flow.open}
	onclose={() => flow.close()}
	{title}
	{description}
	mode="decision"
	verb="Merge"
	busyVerb="Merging…"
	busy={merging}
	disabled={!flow.canConfirm}
	onsubmit={() => flow.confirm()}
	{feedback}
	width="lg"
>
	{#if flow.preview === null}
		<EntityPicker
			{items}
			label={`Merge into: ${label}`}
			placeholder="Find a target…"
			selectedId={flow.targetId}
			onselect={(id) => void flow.choose(id)}
		/>
	{:else}
		<div class="flex items-center justify-between gap-2">
			<span>
				<span class="text-muted-foreground">Merge into </span>
				<span class="font-medium">{target}</span>
			</span>
			<ActionButton variant="ghost" disabled={merging} onclick={() => flow.rechoose()}>
				Choose another target
			</ActionButton>
		</div>
	{/if}

	{#if flow.status === 'previewing'}
		<p class="text-muted-foreground" aria-busy="true">Checking what would change…</p>
	{:else if flow.preview}
		<div class="flex flex-col gap-1.5" data-slot="merge-preview">
			{@render summary(flow.preview)}
		</div>
	{/if}
</ActionDialog>
