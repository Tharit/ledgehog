<script lang="ts">
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import { describeFailure } from '#lib/dimensions/errors.js';
	import type { TagsStore } from '#lib/tags/store.svelte.js';
	import { tagDeleteText } from '#lib/tags/summary.js';
	import type { Tag } from '#lib/types/domain.js';

	// Delete a tag: a decision dialog (patterns §11.2) that names how many entries lose it; the
	// entries stay. The tag stays in `tag` while the dialog closes so its title does not change
	// under the closing animation. A tag that is already gone closes the dialog: the list reloads.
	let {
		store,
		open,
		tag,
		onclose
	}: { store: TagsStore; open: boolean; tag: Tag | null; onclose: () => void } = $props();

	let busy = $state(false);
	let failure = $state<string | null>(null);

	$effect(() => {
		if (open) failure = null;
	});

	async function confirm() {
		if (!tag) return;
		busy = true;
		failure = null;
		const result = await store.remove(tag);
		busy = false;
		if (result.ok) {
			onclose();
		} else if (result.failure.kind === 'not_found') {
			store.notify(describeFailure(result.failure, 'tag'), true);
			onclose();
		} else {
			failure = describeFailure(result.failure, 'tag');
		}
	}

	const feedback = $derived<DialogFeedback | null>(
		failure ? { kind: 'error', text: failure } : null
	);
</script>

<ActionDialog
	{open}
	{onclose}
	title={`Delete tag “${tag?.name ?? ''}”`}
	description="This cannot be undone."
	mode="decision"
	verb="Delete"
	busyVerb="Deleting…"
	destructive
	{busy}
	onsubmit={confirm}
	{feedback}
>
	{#if tag}<p>{tagDeleteText(tag)}</p>{/if}
</ActionDialog>
