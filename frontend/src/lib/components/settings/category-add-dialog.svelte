<script lang="ts">
	import type { CategoriesStore } from '#lib/categories/store.svelte.js';
	import type { CategoryKind } from '#lib/categories/tree.js';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import Field from '#lib/components/common/field.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import { describeFailure, isFieldFailure } from '#lib/dimensions/errors.js';
	import type { Category } from '#lib/types/domain.js';

	// "Add category" and "Add subcategory to Food": a form dialog (patterns §11.2). A top-level
	// category chooses its kind here, a subcategory takes its parent's. A taken name is said under
	// the name; any other refusal in the dialog. After an add the caller reveals the new row, so
	// focus is not given back to the opener.
	let {
		store,
		open,
		parent,
		onclose,
		onadded,
		onclosedafteradd
	}: {
		store: CategoriesStore;
		open: boolean;
		/** the category to add under; `null`: a top-level one */
		parent: Category | null;
		onclose: () => void;
		onadded: (category: Category) => void;
		/** the dialog has finished closing after an add: the place to give focus to the new row */
		onclosedafteradd?: () => void;
	} = $props();

	let name = $state('');
	let kind = $state<CategoryKind>('expense');
	let nameError = $state<string | null>(null);
	let failure = $state<string | null>(null);
	let busy = $state(false);
	let added = false;

	$effect(() => {
		if (!open) return;
		name = '';
		kind = 'expense';
		nameError = null;
		failure = null;
		added = false;
	});

	async function add() {
		const trimmed = name.trim();
		if (trimmed === '') return;
		busy = true;
		nameError = null;
		failure = null;
		const result = await store.create(trimmed, parent ? { parentId: parent.id } : { kind });
		busy = false;
		if (result.ok) {
			added = true;
			onadded(result.value);
			return;
		}
		const text = describeFailure(result.failure, 'category', trimmed);
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
	title={parent ? `Add subcategory to ${parent.name}` : 'Add category'}
	verb="Add"
	busyVerb="Adding…"
	{busy}
	disabled={name.trim() === ''}
	onsubmit={add}
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
	{#if !parent}
		<Field
			group
			label="Kind"
			hint="The kind cannot be changed later; subcategories take their parent's."
		>
			<div class="flex items-center gap-4">
				<label class="flex items-center gap-1.5">
					<input type="radio" class="accent-primary" bind:group={kind} value="expense" />
					Expense
				</label>
				<label class="flex items-center gap-1.5">
					<input type="radio" class="accent-primary" bind:group={kind} value="income" />
					Income
				</label>
			</div>
		</Field>
	{/if}
</ActionDialog>
