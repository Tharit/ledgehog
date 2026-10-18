<script lang="ts">
	import ActionDialog from '#lib/components/common/action-dialog.svelte';

	// "Stop sync…" (ux/views/sync.md "Prompts"): a decision dialog. Nothing more is written, a fetch
	// under way is discarded, the login under way keeps its remaining accounts as failed runs, and
	// logins not reached are left alone. Cancel is focused and Enter never confirms (patterns §11.2).
	let {
		open,
		busy = false,
		error = null,
		onclose,
		onstop
	}: {
		open: boolean;
		busy?: boolean;
		/** the abort could not be sent */
		error?: string | null;
		onclose: () => void;
		onstop: () => void;
	} = $props();
</script>

<ActionDialog
	{open}
	{onclose}
	mode="decision"
	destructive
	title="Stop the sync?"
	verb="Stop sync"
	busyVerb="Stopping…"
	{busy}
	onsubmit={onstop}
	feedback={error ? { kind: 'error', text: error } : null}
>
	<p>
		Nothing more is written. A fetch under way is discarded, the login under way keeps its remaining
		accounts as failed runs, and logins not reached are left alone.
	</p>
</ActionDialog>
