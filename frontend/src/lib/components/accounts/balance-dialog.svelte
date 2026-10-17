<script lang="ts">
	import { untrack } from 'svelte';
	import { BalanceFlow } from '#lib/accounts/balance-flow.svelte.js';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import DateField from '#lib/components/common/date-field.svelte';
	import Field from '#lib/components/common/field.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import type { Account, RecordWriteOut, StatementRecord } from '#lib/types/domain.js';

	// "Set balance" (spec §5.10): a form dialog with the date, defaulting to today, and the balance.
	// Opened on a manual record from the statement it edits that record. Its help text says what a
	// record counts: everything dated on that day. On a date that already holds a manual record it
	// edits that record.
	let {
		open,
		account,
		record = null,
		today,
		locale = 'en',
		flow = new BalanceFlow(),
		onclose,
		onsaved
	}: {
		open: boolean;
		account: Pick<Account, 'id' | 'currency'>;
		/** the manual record to edit; null: set a balance */
		record?: StatementRecord | null;
		today: string;
		locale?: string;
		flow?: BalanceFlow;
		onclose: () => void;
		onsaved: (out: RecordWriteOut) => void;
	} = $props();

	$effect(() => {
		if (!open) return;
		untrack(() => flow.start(account, { today, locale, record: record ?? undefined }));
	});

	async function save() {
		const out = await flow.submit();
		if (out) onsaved(out);
	}

	const feedback = $derived<DialogFeedback | null>(
		flow.failure ? { kind: 'error', text: flow.failure } : null
	);
</script>

<ActionDialog
	{open}
	{onclose}
	title={record ? 'Edit balance' : 'Set balance'}
	verb="Save"
	busyVerb="Saving…"
	busy={flow.busy}
	disabled={!flow.canSubmit}
	onsubmit={save}
	{feedback}
>
	<Field label="Date" error={flow.errors.date ?? null}>
		{#snippet children(field)}
			<DateField {...field} label="Date" bind:value={flow.date} {locale} disabled={flow.busy} />
		{/snippet}
	</Field>
	<Field
		label={`Balance (${account.currency})`}
		hint="The record counts everything dated on that day."
		error={flow.errors.balance ?? null}
	>
		{#snippet children(field)}
			<Input
				bind:value={flow.balanceText}
				{...field}
				inputmode="decimal"
				autocomplete="off"
				readonly={flow.busy}
			/>
		{/snippet}
	</Field>
</ActionDialog>
