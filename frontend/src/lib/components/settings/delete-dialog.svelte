<script lang="ts" generics="Out extends { deletable: boolean }">
	import type { Snippet } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import type { DeleteFlow } from '#lib/dimensions/flows.svelte.js';

	// The delete dialog both dimensions share: it asks the server first (`dry_run`) and shows what
	// stands in the way (then offers "Merge instead…") or what the delete takes with it (then an
	// explicit "Delete"). Deleting cannot be undone.
	let {
		flow,
		title,
		body,
		onmerge
	}: {
		flow: DeleteFlow<Out>;
		title: string;
		/** what the preview says, deletable or not */
		body: Snippet<[Out]>;
		/** "Merge instead…": the caller opens the merge dialog for this one */
		onmerge: () => void;
	} = $props();

	const deleting = $derived(flow.status === 'deleting');
</script>

<Dialog.Root
	open={flow.open}
	onOpenChange={(next) => {
		if (!next) flow.close();
	}}
>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>{title}</Dialog.Title>
			<Dialog.Description>This cannot be undone.</Dialog.Description>
		</Dialog.Header>

		{#if flow.preview === null && flow.failure === null}
			<p class="text-sm text-muted-foreground" aria-busy="true">Checking what would change…</p>
		{:else if flow.preview}
			<div class="flex flex-col gap-1.5 text-sm" data-slot="delete-preview">
				{@render body(flow.preview)}
			</div>
		{/if}

		{#if flow.message}
			<p role="alert" class="text-sm text-destructive">{flow.message}</p>
		{/if}

		<Dialog.Footer>
			<Button variant="outline" disabled={deleting} onclick={() => flow.close()}>Cancel</Button>
			{#if flow.preview && !flow.preview.deletable}
				<Button onclick={onmerge}>Merge instead…</Button>
			{:else}
				<Button variant="destructive" disabled={!flow.canConfirm} onclick={() => flow.confirm()}>
					{deleting ? 'Deleting…' : 'Delete'}
				</Button>
			{/if}
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
