<script lang="ts">
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import Field from '#lib/components/common/field.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import { describeFailure, isFieldFailure } from '#lib/dimensions/errors.js';
	import type { PayeesStore } from '#lib/payees/store.svelte.js';
	import type { Payee } from '#lib/types/domain.js';

	// "Add payee" and "Edit REWE": one form dialog for both (patterns §11.2), name and note, each
	// with its label. A taken name is said under the name; any other refusal in the dialog. After
	// an add the caller reveals the new row, so focus is not given back to the opener.
	let {
		store,
		open,
		payee,
		onclose,
		onsaved,
		onclosedafteradd
	}: {
		store: PayeesStore;
		open: boolean;
		/** the payee to edit; `null`: add a new one */
		payee: Payee | null;
		onclose: () => void;
		onsaved: (payee: Payee, added: boolean) => void;
		/** the dialog has finished closing after an add: the place to give focus to the new row */
		onclosedafteradd?: () => void;
	} = $props();

	let name = $state('');
	let note = $state('');
	let nameError = $state<string | null>(null);
	let failure = $state<string | null>(null);
	let busy = $state(false);
	let added = false;

	$effect(() => {
		if (!open) return;
		name = payee?.name ?? '';
		note = payee?.note ?? '';
		nameError = null;
		failure = null;
		added = false;
	});

	async function save() {
		const trimmed = name.trim();
		if (trimmed === '') return;
		const trimmedNote = note.trim() === '' ? null : note.trim();
		if (payee && trimmed === payee.name && trimmedNote === (payee.note ?? null)) {
			onclose();
			return;
		}
		busy = true;
		nameError = null;
		failure = null;
		const result = payee
			? await store.update(payee.id, { name: trimmed, note: trimmedNote })
			: await store.create(trimmed, trimmedNote);
		busy = false;
		if (result.ok) {
			added = payee === null;
			onsaved(result.value, payee === null);
			return;
		}
		const text = describeFailure(result.failure, 'payee', trimmed);
		if (isFieldFailure(result.failure)) nameError = text;
		else failure = text;
	}

	const feedback = $derived<DialogFeedback | null>(
		failure ? { kind: 'error', text: failure } : null
	);
</script>

<ActionDialog
	{open}
	{onclose}
	title={payee ? `Edit ${payee.name}` : 'Add payee'}
	verb={payee ? 'Save' : 'Add'}
	busyVerb={payee ? 'Saving…' : 'Adding…'}
	{busy}
	disabled={name.trim() === ''}
	onsubmit={save}
	{feedback}
	oncloseautofocus={(event) => {
		if (!added) return;
		event.preventDefault();
		added = false;
		onclosedafteradd?.();
	}}
>
	<Field label="Name" error={nameError}>
		{#snippet children(field)}
			<Input bind:value={name} {...field} readonly={busy} autocomplete="off" />
		{/snippet}
	</Field>
	<Field label="Note" hint="Optional: what this merchant is for.">
		{#snippet children(field)}
			<Input bind:value={note} {...field} readonly={busy} autocomplete="off" />
		{/snippet}
	</Field>
</ActionDialog>
