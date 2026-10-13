<script lang="ts" generics="Out extends { deletable: boolean }">
	import type { Snippet } from 'svelte';
	import ActionDialog from '#lib/components/common/action-dialog.svelte';
	import type { DeleteFlow } from '#lib/dimensions/flows.svelte.js';

	// The delete dialog both dimensions share, a decision dialog: it asks the server first
	// (`dry_run`) and shows what stands in the way (then the verb is "Merge instead…") or what the
	// delete takes with it (then an explicit "Delete", focus on Cancel). Deleting cannot be undone.
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

	const blocked = $derived(flow.preview !== null && !flow.preview.deletable);
</script>

<ActionDialog
	open={flow.open}
	onclose={() => flow.close()}
	{title}
	description="This cannot be undone."
	mode="decision"
	verb={blocked ? 'Merge instead…' : 'Delete'}
	busyVerb="Deleting…"
	destructive={!blocked}
	busy={flow.status === 'deleting'}
	disabled={!blocked && !flow.canConfirm}
	onsubmit={() => (blocked ? onmerge() : flow.confirm())}
	feedback={flow.message ? { kind: 'error', text: flow.message } : null}
>
	{#if flow.preview === null && flow.failure === null}
		<p class="text-muted-foreground" aria-busy="true">Checking what would change…</p>
	{:else if flow.preview}
		<div class="flex flex-col gap-1.5" data-slot="delete-preview">
			{@render body(flow.preview)}
		</div>
	{/if}
</ActionDialog>
