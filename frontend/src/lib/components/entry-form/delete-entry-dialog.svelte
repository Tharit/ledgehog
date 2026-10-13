<script lang="ts">
	import { untrack } from 'svelte';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import type { EditTarget } from '#lib/entry-form/controller.svelte.js';
	import { DeleteFlow } from '#lib/entry-form/delete-flow.svelte.js';
	import { describeEntry } from '#lib/entry-form/effects.js';
	import { session } from '#lib/stores/session.svelte.js';

	// "Delete entry": a decision dialog (patterns §11.2). The dry run names what goes before the
	// verb is available; focus starts on Cancel.
	let {
		open,
		target,
		onclose,
		flow = new DeleteFlow()
	}: {
		open: boolean;
		target: EditTarget | null;
		onclose: () => void;
		flow?: DeleteFlow;
	} = $props();

	$effect(() => {
		if (!open || !target) {
			untrack(() => flow.stop());
			return;
		}
		untrack(() => flow.start(target.entry));
		return () => flow.stop();
	});

	async function confirm() {
		if (await flow.confirm()) onclose();
	}

	const feedback = $derived<DialogFeedback | null>(
		flow.feedback
			? {
					kind: flow.feedback.kind,
					text: flow.feedback.text,
					action: flow.feedback.retryable
						? { label: 'Try again', onclick: () => flow.retry() }
						: undefined
				}
			: null
	);
</script>

<ActionDialog
	{open}
	{onclose}
	mode="decision"
	destructive
	title="Delete entry"
	verb="Delete"
	busyVerb="Deleting…"
	busy={flow.busy}
	disabled={!flow.canDelete}
	onsubmit={confirm}
	{feedback}
>
	{#if target}
		<p class="font-medium" data-slot="delete-subject">
			{describeEntry(target.entry, session.config?.locale ?? 'en')}
		</p>
	{/if}
	<p data-slot="delete-summary" class="min-h-5">
		{#if flow.status === 'checking'}
			<span class="text-muted-foreground">Checking what would change…</span>
		{:else if flow.status === 'ready' && flow.summary}
			{flow.summary}
		{/if}
	</p>
</ActionDialog>
