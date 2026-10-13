<script lang="ts">
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import Field from '#lib/components/common/field.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import { describeFailure, isFieldFailure } from '#lib/dimensions/errors.js';
	import type { TagsStore } from '#lib/tags/store.svelte.js';
	import type { Tag } from '#lib/types/domain.js';
	import ColorChoices from './color-choices.svelte';

	// "Add tag": a form dialog (patterns §11.2), the name and an optional colour. A taken name is
	// said under the name; any other refusal in the dialog. After an add the caller reveals the
	// new row, so focus is not given back to the opener.
	let {
		store,
		open,
		onclose,
		onsaved,
		onclosedafteradd
	}: {
		store: TagsStore;
		open: boolean;
		onclose: () => void;
		onsaved: (tag: Tag) => void;
		/** the dialog has finished closing after an add: the place to give focus to the new row */
		onclosedafteradd?: () => void;
	} = $props();

	let name = $state('');
	let color = $state<string | null>(null);
	let nameError = $state<string | null>(null);
	let failure = $state<string | null>(null);
	let busy = $state(false);
	let added = false;

	$effect(() => {
		if (!open) return;
		name = '';
		color = null;
		nameError = null;
		failure = null;
		added = false;
	});

	async function save() {
		const trimmed = name.trim();
		if (trimmed === '') return;
		busy = true;
		nameError = null;
		failure = null;
		const result = await store.create(trimmed, color);
		busy = false;
		if (result.ok) {
			added = true;
			onsaved(result.value);
			return;
		}
		const text = describeFailure(result.failure, 'tag', trimmed);
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
	title="Add tag"
	verb="Add"
	busyVerb="Adding…"
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
	<div class="flex flex-col gap-1.5">
		<span class="text-sm font-medium">Colour</span>
		<ColorChoices {color} clearLabel="None" disabled={busy} onchange={(next) => (color = next)} />
	</div>
</ActionDialog>
