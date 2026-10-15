<script lang="ts">
	import { untrack } from 'svelte';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import Field from '#lib/components/common/field.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import { AddAccountFlow } from '#lib/accounts/add-flow.svelte.js';
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
	description="Entered by hand. Transfers to it can be completed here."
	verb="Add"
	busyVerb="Adding…"
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
			<select
				{...field}
				bind:value={flow.kind}
				disabled={flow.busy}
				class="h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive dark:bg-input/30"
			>
				{#each ACCOUNT_KINDS as option (option.kind)}
					<option value={option.kind}>{option.label}</option>
				{/each}
			</select>
		{/snippet}
	</Field>
	<Field
		label="Currency"
		hint={flow.locked ? 'The transfer needs an account in this currency.' : undefined}
		error={flow.errors.currency ?? null}
	>
		{#snippet children(field)}
			{#if flow.locked}
				<Input value={flow.currency} {...field} readonly autocomplete="off" />
			{:else}
				<select
					{...field}
					bind:value={flow.currency}
					disabled={flow.busy}
					class="h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive dark:bg-input/30"
				>
					{#each flow.currencies as code (code)}
						<option value={code}>{code}</option>
					{/each}
				</select>
			{/if}
		{/snippet}
	</Field>
</ActionDialog>
