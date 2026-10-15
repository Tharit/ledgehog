<script lang="ts">
	import { tick, untrack } from 'svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import Field from '#lib/components/common/field.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import { AMOUNT_HINT } from '#lib/entry-form/amount.js';
	import { AddFlow } from '#lib/entry-form/add-flow.svelte.js';
	import type { AddOptions } from '#lib/entry-form/controller.svelte.js';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';

	// "Add entry": a form dialog (patterns §11.1, §11.2) with the account, date, amount with its sign
	// and the purpose. "Add" enters the transaction, closes and opens the work panel on it; "Add and
	// add another" enters it and keeps the dialog for the next one. No draft survives closing.
	let {
		open,
		options = {},
		onclose,
		flow = new AddFlow()
	}: {
		open: boolean;
		options?: AddOptions;
		onclose: () => void;
		flow?: AddFlow;
	} = $props();

	let amountInput = $state<HTMLInputElement | null>(null);
	let added = false;

	$effect(() => {
		if (!open) return;
		untrack(() => {
			flow.start(options);
			void lookupsStore.ensure().then(() => flow.defaultAccount(options));
		});
	});

	$effect(() => {
		if (flow.focusAmount === 0) return;
		// after the field shows its new text
		void tick().then(() => {
			if (!amountInput) return;
			amountInput.focus();
			// only the sign is there: the caret goes after it; a typed amount is selected to retype
			if (/^\s*[-\u2212+]?\s*$/.test(amountInput.value)) {
				const end = amountInput.value.length;
				amountInput.setSelectionRange(end, end);
			} else amountInput.select();
		});
	});

	async function add() {
		if ((await flow.submit(false)) === 'added') {
			added = true;
			onclose();
		}
	}

	async function addAnother() {
		await flow.submit(true);
	}

	const feedback = $derived<DialogFeedback | null>(
		flow.feedback
			? {
					kind: flow.feedback.kind,
					text: flow.feedback.text,
					action: flow.feedback.retryable
						? { label: 'Try again', onclick: () => void add() }
						: undefined
				}
			: null
	);
	const noAccounts = $derived(lookupsStore.loaded && flow.accounts.length === 0);
</script>

{#snippet another()}
	<ActionButton
		variant="secondary"
		disabled={noAccounts || flow.busy !== null}
		busy={flow.busy === 'another'}
		busyLabel="Adding…"
		onclick={addAnother}
	>
		Add and add another
	</ActionButton>
{/snippet}

<ActionDialog
	{open}
	{onclose}
	title="Add entry"
	verb="Add"
	busyVerb={flow.busy === 'add' ? 'Adding…' : undefined}
	busy={flow.busy !== null}
	disabled={noAccounts}
	onsubmit={add}
	{feedback}
	secondary={another}
	oncloseautofocus={(event) => {
		// the work panel opens on the new unit and takes the focus itself
		if (!added) return;
		event.preventDefault();
		added = false;
	}}
>
	{#if noAccounts}
		<EmptyState title="No account to add to">
			Entries are added by hand only on accounts without a bank connection.
		</EmptyState>
	{:else}
		{#if flow.added}
			<p role="status" class="text-sm text-muted-foreground" data-slot="added-notice">
				{flow.added}
			</p>
		{/if}
		<Field label="Account" error={flow.errors.account ?? null}>
			{#snippet children(field)}
				<select
					{...field}
					bind:value={flow.accountId}
					onchange={() => flow.touch('account')}
					disabled={flow.busy !== null || !lookupsStore.loaded}
					class="h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive dark:bg-input/30"
				>
					{#if flow.accountId === null}<option value={null}></option>{/if}
					{#each flow.accounts as account (account.id)}
						<option value={account.id}>{account.name}</option>
					{/each}
				</select>
			{/snippet}
		</Field>
		<Field label="Date" error={flow.errors.date ?? null}>
			{#snippet children(field)}
				<Input
					type="date"
					bind:value={flow.date}
					{...field}
					readonly={flow.busy !== null}
					oninput={() => flow.touch('date')}
				/>
			{/snippet}
		</Field>
		<Field label="Amount" hint={AMOUNT_HINT} error={flow.errors.amount ?? null}>
			{#snippet children(field)}
				<Input
					bind:ref={amountInput}
					bind:value={flow.amountText}
					{...field}
					inputmode="decimal"
					autocomplete="off"
					readonly={flow.busy !== null}
					oninput={() => flow.touch('amount')}
				/>
			{/snippet}
		</Field>
		<Field label="Purpose" error={flow.errors.purpose ?? null}>
			{#snippet children(field)}
				<Input
					bind:value={flow.purpose}
					{...field}
					autocomplete="off"
					readonly={flow.busy !== null}
					oninput={() => flow.touch('purpose')}
				/>
			{/snippet}
		</Field>
	{/if}
</ActionDialog>
