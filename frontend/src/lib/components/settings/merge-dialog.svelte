<script lang="ts" generics="Out extends { entry_count: number }">
	import type { Snippet } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import type { MergeFlow } from '#lib/dimensions/flows.svelte.js';
	import EntityPicker, { type PickerItem } from './entity-picker.svelte';

	// The merge dialog both dimensions share (spec §3.5, §3.6): choose the target, read the
	// server's dry run, merge explicitly. The consequence list is the caller's `summary`; nothing
	// is written until "Merge" is pressed, and the count the preview showed goes with it.
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
</script>

<Dialog.Root
	open={flow.open}
	onOpenChange={(next) => {
		if (!next) flow.close();
	}}
>
	<Dialog.Content class="sm:max-w-lg">
		<Dialog.Header>
			<Dialog.Title>{title}</Dialog.Title>
			<Dialog.Description>{description}</Dialog.Description>
		</Dialog.Header>

		{#if flow.preview === null}
			<EntityPicker
				{items}
				label={`Merge into: ${label}`}
				placeholder="Find a target…"
				selectedId={flow.targetId}
				onselect={(id) => void flow.choose(id)}
			/>
		{:else}
			<div class="flex items-center justify-between gap-2 text-sm">
				<span>
					<span class="text-muted-foreground">Merge into </span>
					<span class="font-medium">{target}</span>
				</span>
				<Button variant="ghost" size="sm" disabled={merging} onclick={() => flow.rechoose()}>
					Choose another target
				</Button>
			</div>
		{/if}

		{#if flow.status === 'previewing'}
			<p class="text-sm text-muted-foreground" aria-busy="true">Checking what would change…</p>
		{:else if flow.preview}
			<div class="flex flex-col gap-1.5 text-sm" data-slot="merge-preview">
				{@render summary(flow.preview)}
			</div>
		{/if}

		{#if flow.moved}
			<p role="status" class="text-sm">{flow.moved}</p>
		{/if}
		{#if flow.message}
			<p role="alert" class="text-sm text-destructive">{flow.message}</p>
		{/if}

		<Dialog.Footer>
			<Button variant="outline" disabled={merging} onclick={() => flow.close()}>Cancel</Button>
			<Button disabled={!flow.canConfirm} onclick={() => flow.confirm()}>
				{merging ? 'Merging…' : 'Merge'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
