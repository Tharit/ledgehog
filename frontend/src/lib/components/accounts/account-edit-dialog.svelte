<script lang="ts">
	import { untrack } from 'svelte';
	import { EditAccountFlow } from '#lib/accounts/edit-flow.svelte.js';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import Field from '#lib/components/common/field.svelte';
	import ColorChoices from '#lib/components/settings/color-choices.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import { ACCOUNT_ICONS } from '#lib/theme/icon-sets.js';
	import { iconFor } from '#lib/theme/icons.js';
	import type { Account, AccountWriteOut } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';

	// "Edit" on the account (ux/views/account.md): name, external reference, note, icon and colour in
	// one form dialog. Kind and currency are not edited here (spec I38). Only what changed is sent.
	let {
		open,
		account,
		flow = new EditAccountFlow(),
		onclose,
		onsaved
	}: {
		open: boolean;
		account: Account | null;
		flow?: EditAccountFlow;
		onclose: () => void;
		onsaved: (out: AccountWriteOut) => void;
	} = $props();

	$effect(() => {
		if (!open || !account) return;
		const shown = account;
		untrack(() => flow.start(shown));
	});

	async function save() {
		if (Object.keys(flow.changes).length === 0) {
			onclose();
			return;
		}
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
	title={account ? `Edit ${account.name}` : 'Edit account'}
	verb="Save"
	busyVerb="Saving…"
	busy={flow.busy}
	disabled={!flow.canSubmit}
	onsubmit={save}
	{feedback}
>
	<Field label="Name" error={flow.errors.name ?? null}>
		{#snippet children(field)}
			<Input bind:value={flow.name} {...field} readonly={flow.busy} autocomplete="off" />
		{/snippet}
	</Field>
	<Field
		label="External reference"
		hint="Optional: the bank's own reference for this account, such as its IBAN."
		error={flow.errors.externalRef ?? null}
	>
		{#snippet children(field)}
			<Input bind:value={flow.externalRef} {...field} readonly={flow.busy} autocomplete="off" />
		{/snippet}
	</Field>
	<Field label="Note">
		{#snippet children(field)}
			<Input bind:value={flow.note} {...field} readonly={flow.busy} autocomplete="off" />
		{/snippet}
	</Field>
	<Field label="Icon" group>
		<div class="flex flex-wrap gap-1" role="group" aria-label="Icon">
			<button
				type="button"
				class={cn(
					'h-8 rounded-md border px-2 text-xs',
					flow.icon === null ? 'border-primary bg-accent' : 'border-border hover:bg-muted'
				)}
				aria-pressed={flow.icon === null}
				disabled={flow.busy}
				onclick={() => (flow.icon = null)}
			>
				Kind’s icon
			</button>
			{#each ACCOUNT_ICONS as option (option)}
				{@const Icon = iconFor(option)}
				<button
					type="button"
					class={cn(
						'inline-flex size-8 items-center justify-center rounded-md border',
						flow.icon === option ? 'border-primary bg-accent' : 'border-transparent hover:bg-muted'
					)}
					aria-label={option}
					title={option}
					aria-pressed={flow.icon === option}
					disabled={flow.busy}
					onclick={() => (flow.icon = option)}
				>
					<Icon size={16} strokeWidth={1.75} aria-hidden="true" />
				</button>
			{/each}
		</div>
	</Field>
	<Field label="Colour" group>
		<ColorChoices
			color={flow.color}
			clearLabel="Default"
			disabled={flow.busy}
			onchange={(next) => (flow.color = next)}
		/>
	</Field>
</ActionDialog>
