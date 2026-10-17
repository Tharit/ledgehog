<script lang="ts">
	import { untrack } from 'svelte';
	import { CloseAccountFlow } from '#lib/accounts/lifecycle-flow.svelte.js';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import DateField from '#lib/components/common/date-field.svelte';
	import Field from '#lib/components/common/field.svelte';
	import type { Account, AccountWriteOut } from '#lib/types/domain.js';

	// "Close…" an account (spec §3.3): a decision dialog with the closing date, default today. A
	// closed account stops fetching and its history stays; it can be reopened.
	let {
		open,
		account,
		today,
		locale = 'en',
		flow = new CloseAccountFlow(),
		onclose,
		onclosed
	}: {
		open: boolean;
		account: Account | null;
		today: string;
		locale?: string;
		flow?: CloseAccountFlow;
		onclose: () => void;
		onclosed: (out: AccountWriteOut) => void;
	} = $props();

	$effect(() => {
		if (!open || !account) return;
		const shown = account;
		untrack(() => flow.start(shown, today));
	});

	async function confirm() {
		const out = await flow.confirm();
		if (out) onclosed(out);
	}

	const feedback = $derived<DialogFeedback | null>(
		flow.failure ? { kind: flow.failure.kind, text: flow.failure.text } : null
	);
</script>

<ActionDialog
	{open}
	{onclose}
	mode="decision"
	title={account ? `Close ${account.name}` : 'Close account'}
	description="A closed account stops fetching and holds no balance after its closing date. Its history stays, and it can be reopened."
	verb="Close account"
	busyVerb="Closing…"
	busy={flow.busy}
	disabled={!flow.canSubmit}
	onsubmit={confirm}
	{feedback}
>
	<Field label="Closing date">
		{#snippet children(field)}
			<DateField
				{...field}
				label="Closing date"
				bind:value={flow.date}
				{locale}
				disabled={flow.busy}
			/>
		{/snippet}
	</Field>
</ActionDialog>
