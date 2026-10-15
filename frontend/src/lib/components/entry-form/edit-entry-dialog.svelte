<script lang="ts">
	import { untrack } from 'svelte';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import DateField from '#lib/components/common/date-field.svelte';
	import Field from '#lib/components/common/field.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import type { EditTarget } from '#lib/entry-form/controller.svelte.js';
	import { AMOUNT_HINT } from '#lib/entry-form/amount.js';
	import { EditFlow } from '#lib/entry-form/edit-flow.svelte.js';
	import { EDIT_WARNING } from '#lib/entry-form/effects.js';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';
	import { session } from '#lib/stores/session.svelte.js';

	// "Edit entry": the same fields as adding, the account fixed (spec §5.6). The static warning above
	// Save is the confirmation (D214); the dry run lists what this edit would do before Save is
	// available, and Save carries the versions it reported.
	let {
		open,
		target,
		onclose,
		flow = new EditFlow()
	}: {
		open: boolean;
		target: EditTarget | null;
		onclose: () => void;
		flow?: EditFlow;
	} = $props();

	$effect(() => {
		if (!open || !target) {
			untrack(() => flow.stop());
			return;
		}
		untrack(() => flow.start(target));
		return () => flow.stop();
	});

	// every change of a field is checked again after a pause
	$effect(() => {
		void flow.fingerprint;
		untrack(() => flow.schedule());
	});

	async function save() {
		if (await flow.save()) onclose();
	}

	const accountName = $derived(
		target ? (lookupsStore.lookups.accounts.get(target.entry.account_id)?.name ?? '') : ''
	);
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
	title="Edit entry"
	verb="Save"
	busyVerb="Saving…"
	busy={flow.busy}
	disabled={!flow.canSave}
	onsubmit={save}
	{feedback}
>
	<Field group label="Account" hint="An entry stays on its account.">
		<p data-slot="edit-account">{accountName}</p>
	</Field>
	<Field label="Date" error={flow.errors.date ?? null}>
		{#snippet children(field)}
			<DateField
				{...field}
				label="Date"
				bind:value={flow.date}
				locale={session.config?.locale}
				disabled={flow.busy}
			/>
		{/snippet}
	</Field>
	<Field label="Amount" hint={AMOUNT_HINT} error={flow.errors.amount ?? null}>
		{#snippet children(field)}
			<Input
				bind:value={flow.amountText}
				{...field}
				inputmode="decimal"
				autocomplete="off"
				readonly={flow.busy}
			/>
		{/snippet}
	</Field>
	<Field label="Purpose" error={flow.errors.purpose ?? null}>
		{#snippet children(field)}
			<Input bind:value={flow.purpose} {...field} autocomplete="off" readonly={flow.busy} />
		{/snippet}
	</Field>

	<div data-slot="edit-consequences" class="min-h-5 text-sm">
		{#if flow.status === 'checking'}
			<p class="text-muted-foreground">Checking what would change…</p>
		{:else if flow.status === 'ready' && flow.lines.length > 0}
			<ul class="flex list-disc flex-col gap-0.5 pl-5">
				{#each flow.lines as line, i (i)}<li>{line}</li>{/each}
			</ul>
		{/if}
	</div>
	<p data-slot="edit-warning" class="text-sm text-muted-foreground">{EDIT_WARNING}</p>
</ActionDialog>
