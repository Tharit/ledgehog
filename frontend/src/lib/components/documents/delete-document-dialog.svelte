<script lang="ts">
	import { untrack } from 'svelte';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import { DeleteDocumentFlow } from '#lib/documents/delete-flow.svelte.js';
	import type { DocumentDetail } from '#lib/types/domain.js';

	// "Delete…" a document (spec §5.5, ux/views/documents.md): says what goes with it, and that its
	// importer may deliver it again.
	let {
		open,
		document,
		accountName = null,
		flow = new DeleteDocumentFlow(),
		onclose,
		ondeleted
	}: {
		open: boolean;
		document: DocumentDetail;
		/** the name of the account the document is booked on, where it is booked */
		accountName?: string | null;
		flow?: DeleteDocumentFlow;
		onclose: () => void;
		ondeleted: () => void;
	} = $props();

	$effect(() => {
		if (!open) return;
		const id = document.id;
		untrack(() => flow.start(id));
	});

	async function confirm() {
		if (await flow.confirm()) ondeleted();
	}

	const feedback = $derived<DialogFeedback | null>(
		flow.failure ? { kind: flow.failure.kind, text: flow.failure.text } : null
	);
</script>

<ActionDialog
	{open}
	{onclose}
	mode="decision"
	destructive
	title="Delete this document"
	verb="Delete"
	busyVerb="Deleting…"
	busy={flow.busy}
	onsubmit={confirm}
	{feedback}
>
	<div class="flex flex-col gap-2">
		<p>
			The document goes{#if document.booking}, and so does its booking on {accountName ??
					`account ${document.booking.account_id}`} with all its entries, confirmed ones included{/if}.
		</p>
		<p>Its importer may deliver it again; the email importer does so after a Reset.</p>
	</div>
</ActionDialog>
