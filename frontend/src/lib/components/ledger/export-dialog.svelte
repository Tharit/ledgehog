<script lang="ts">
	import ActionDialog from '#lib/components/common/action-dialog.svelte';

	// "Export CSV…" asks before it downloads (patterns §11.1): the file is whatever the ledger's
	// filters show when "Download" is pressed, so the caller builds the address then (`onconfirm`).
	let { open, onclose, onconfirm }: { open: boolean; onclose: () => void; onconfirm: () => void } =
		$props();
</script>

<ActionDialog
	{open}
	{onclose}
	title="Export CSV"
	mode="decision"
	verb="Download"
	onsubmit={onconfirm}
>
	<p>
		Downloads every entry that matches the ledger's current filters as a CSV file. Change the
		filters first to export a different set.
	</p>
</ActionDialog>
