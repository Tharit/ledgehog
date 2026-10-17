<script lang="ts">
	import { untrack } from 'svelte';
	import { DeleteAccountFlow } from '#lib/accounts/lifecycle-flow.svelte.js';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import type { Account } from '#lib/types/domain.js';

	// "Delete…" an account (spec §3.3): only an account that holds nothing can be deleted. The server
	// refuses otherwise; the dialog then says what the account holds and offers "Close…" instead.
	let {
		open,
		account,
		flow = new DeleteAccountFlow(),
		onclose,
		ondeleted,
		onclosewith
	}: {
		open: boolean;
		account: Account | null;
		flow?: DeleteAccountFlow;
		onclose: () => void;
		ondeleted: () => void;
		/** the refusal's "Close…": leave this dialog for the close decision */
		onclosewith: () => void;
	} = $props();

	$effect(() => {
		if (!open || !account) return;
		const shown = account;
		untrack(() => flow.start(shown));
	});

	async function confirm() {
		if (await flow.confirm()) ondeleted();
	}

	const feedback = $derived<DialogFeedback | null>(
		flow.failure
			? {
					kind: flow.failure.kind,
					text: flow.failure.text,
					action:
						flow.failure.reason === 'account_not_empty'
							? { label: 'Close…', onclick: onclosewith }
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
	title={account ? `Delete ${account.name}` : 'Delete account'}
	verb="Delete"
	busyVerb="Deleting…"
	busy={flow.busy}
	onsubmit={confirm}
	{feedback}
>
	<p>Only an account that holds nothing can be deleted. If it holds anything, close it instead.</p>
</ActionDialog>
