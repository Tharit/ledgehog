<script lang="ts">
	import { untrack } from 'svelte';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import ChoiceSelect from '#lib/components/common/choice-select.svelte';
	import Field from '#lib/components/common/field.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import { AddAccountFlow } from '#lib/accounts/add-flow.svelte.js';
	import { EXTERNAL_REF_HINT, EXTERNAL_REF_LABEL } from '#lib/accounts/external-ref.js';
	import { accounts } from '#lib/accounts/controller.svelte.js';
	import { ACCOUNT_KINDS } from '#lib/accounts/kinds.js';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';

	// "Add account": a form dialog (patterns §11.1, §11.2), opened by the account controller from the
	// review queue and from the work panel's counter-account picker. A currency the caller needs is
	// shown locked. Adding puts the account in the shared lists and tells the caller.
	let {
		open,
		onclose,
		flow = new AddAccountFlow()
	}: {
		open: boolean;
		onclose: () => void;
		flow?: AddAccountFlow;
	} = $props();

	$effect(() => {
		if (!open) return;
		untrack(() => {
			flow.start(accounts.options);
			void lookupsStore.ensure();
		});
	});

	async function add() {
		const account = await flow.submit();
		if (!account) return;
		accounts.added(account);
	}

	const feedback = $derived<DialogFeedback | null>(
		flow.failure ? { kind: 'error', text: flow.failure } : null
	);
</script>

<ActionDialog
	{open}
	{onclose}
	title="Add account"
	description={accounts.options.description ??
		'Entered by hand. Transfers to it can be completed here.'}
	verb={accounts.options.verb ?? 'Add'}
	busyVerb={accounts.options.busyVerb ?? 'Adding…'}
	busy={flow.busy}
	disabled={!flow.canSubmit}
	onsubmit={add}
	{feedback}
	oncloseautofocus={(event) => {
		// the opener may be gone (an item of a closed popover): focus goes where the opener said
		const target = accounts.opener;
		if (target && target.isConnected) {
			event.preventDefault();
			target.focus();
		}
	}}
>
	<Field label="Name" error={flow.errors.name ?? null}>
		{#snippet children(field)}
			<Input bind:value={flow.name} {...field} readonly={flow.busy} autocomplete="off" />
		{/snippet}
	</Field>
	<Field label="Kind">
		{#snippet children(field)}
			<ChoiceSelect
				{...field}
				label="Kind"
				value={flow.kind}
				options={ACCOUNT_KINDS.map((o) => ({ value: o.kind, label: o.label }))}
				disabled={flow.busy}
				onchange={(next) => (flow.kind = next as typeof flow.kind)}
			/>
		{/snippet}
	</Field>
	<Field
		label="Currency"
		hint={flow.locked
			? (accounts.options.currencyHint ?? 'The transfer needs an account in this currency.')
			: undefined}
		error={flow.errors.currency ?? null}
	>
		{#snippet children(field)}
			{#if flow.locked}
				<Input value={flow.currency} {...field} readonly autocomplete="off" />
			{:else}
				<ChoiceSelect
					{...field}
					label="Currency"
					value={flow.currency}
					options={flow.currencies.map((code) => ({ value: code, label: code }))}
					disabled={flow.busy}
					onchange={(next) => (flow.currency = next)}
				/>
			{/if}
		{/snippet}
	</Field>
	<Field
		label={EXTERNAL_REF_LABEL}
		hint={EXTERNAL_REF_HINT}
		error={flow.errors.externalRef ?? null}
	>
		{#snippet children(field)}
			<Input bind:value={flow.externalRef} {...field} readonly={flow.busy} autocomplete="off" />
		{/snippet}
	</Field>
</ActionDialog>
