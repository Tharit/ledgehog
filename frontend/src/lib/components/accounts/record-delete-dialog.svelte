<script lang="ts">
	import { untrack } from 'svelte';
	import { RecordDeleteFlow } from '#lib/accounts/record-delete-flow.svelte.js';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import { recordKindLabel } from '#lib/accounts/statement.js';
	import { formatDate, formatMoney } from '#lib/format/index.js';
	import type { RecordDeleteOut, StatementRecord } from '#lib/types/domain.js';

	// "Delete…" a balance record (spec §3.10): a decision dialog that says what deleting does. The
	// record's interval merges into the next record's, so what it explained is explained, or not,
	// by that one. A decision about something destructive starts on Cancel.
	let {
		open,
		record,
		locale = 'en',
		flow = new RecordDeleteFlow(),
		onclose,
		ondeleted
	}: {
		open: boolean;
		record: StatementRecord | null;
		locale?: string;
		flow?: RecordDeleteFlow;
		onclose: () => void;
		ondeleted: (out: RecordDeleteOut) => void;
	} = $props();

	$effect(() => {
		if (!open || !record) return;
		const shown = record;
		untrack(() => flow.start(shown));
	});

	async function confirm() {
		const out = await flow.confirm();
		if (out) ondeleted(out);
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
	title="Delete balance record"
	verb="Delete"
	busyVerb="Deleting…"
	busy={flow.busy}
	onsubmit={confirm}
	{feedback}
>
	{#if record}
		<p class="font-medium" data-slot="record-subject">
			{recordKindLabel(record)} · {formatDate(record.balance_on, locale)} ·
			{formatMoney(record.balance.amount, record.balance.currency, {
				locale,
				showCurrency: true,
				showPlus: false
			})}
		</p>
	{/if}
	<p>
		The rows since the previous record are then counted toward the next record: its interval grows
		to take in this one, and the derived entries are worked out again.
	</p>
</ActionDialog>
