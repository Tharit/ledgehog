<script lang="ts">
	import GitMergeIcon from '@lucide/svelte/icons/git-merge';
	import PencilIcon from '@lucide/svelte/icons/pencil';
	import Trash2Icon from '@lucide/svelte/icons/trash-2';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { describeFailure } from '#lib/dimensions/errors.js';
	import type { PayeesStore } from '#lib/payees/store.svelte.js';
	import { PAYEE_ICONS } from '#lib/theme/icon-sets.js';
	import { resolvePayee } from '#lib/theme/resolve.js';
	import type { Payee } from '#lib/types/domain.js';
	import LookPicker from './look-picker.svelte';

	// One payee (comfortable density, design §5): its look (the initial stands in for a missing
	// icon, "default" says so when the look is not its own), name and note, with edit, merge and
	// delete. The document provider is not shown: it arrives with documents (decision C9).
	let { payee, store }: { payee: Payee; store: PayeesStore } = $props();

	const look = $derived(resolvePayee(payee));
	const isDefault = $derived(look.icon === null && payee.color === null);

	let editing = $state(false);
	let nameDraft = $state('');
	let noteDraft = $state('');
	let error = $state<string | null>(null);
	let busy = $state(false);
	let nameInput = $state<HTMLInputElement | null>(null);

	$effect(() => {
		if (editing) nameInput?.focus();
	});

	function start() {
		nameDraft = payee.name;
		noteDraft = payee.note ?? '';
		error = null;
		editing = true;
	}

	async function save() {
		const name = nameDraft.trim();
		const note = noteDraft.trim() === '' ? null : noteDraft.trim();
		if (name === '') return;
		if (name === payee.name && note === (payee.note ?? null)) {
			editing = false;
			return;
		}
		busy = true;
		const result = await store.update(payee.id, { name, note });
		busy = false;
		if (result.ok) editing = false;
		else error = describeFailure(result.failure, 'payee', name);
	}

	async function changeLook(patch: { icon?: string | null; color?: string | null }) {
		const result = await store.update(payee.id, patch);
		if (!result.ok) store.notify(describeFailure(result.failure, 'payee'), true);
	}
</script>

<li data-slot="payee-row" data-payee-id={payee.id}>
	<div class="flex min-h-12 items-center gap-3 border-b border-border py-1">
		<LookPicker
			name={payee.name}
			icon={payee.icon}
			color={payee.color}
			icons={PAYEE_ICONS}
			shownIcon={look.icon}
			shownColor={look.color}
			initial={look.initial}
			clearLabel="Default"
			onchange={changeLook}
		/>

		{#if editing}
			<form
				class="flex min-w-0 flex-1 flex-wrap items-start gap-2"
				onsubmit={(event) => {
					event.preventDefault();
					void save();
				}}
			>
				<div class="flex min-w-48 flex-1 flex-col gap-1">
					<Input
						bind:ref={nameInput}
						bind:value={nameDraft}
						aria-label={`Name of ${payee.name}`}
						aria-invalid={error !== null}
						disabled={busy}
						onkeydown={(event) => {
							if (event.key === 'Escape') {
								event.stopPropagation();
								editing = false;
							}
						}}
					/>
					{#if error}
						<span role="alert" class="text-xs text-destructive">{error}</span>
					{/if}
				</div>
				<Input
					bind:value={noteDraft}
					placeholder="Note"
					aria-label={`Note on ${payee.name}`}
					disabled={busy}
					class="min-w-48 flex-1"
				/>
				<Button type="submit" size="sm" disabled={busy || nameDraft.trim() === ''}>Save</Button>
				<Button variant="ghost" size="sm" onclick={() => (editing = false)}>Cancel</Button>
			</form>
		{:else}
			<div class="flex min-w-0 flex-1 flex-col">
				<span class="truncate text-sm font-medium">{payee.name}</span>
				<span class="truncate text-xs text-muted-foreground">
					{#if isDefault}<span data-slot="look-hint">default</span>{/if}
					{#if isDefault && payee.note}·{/if}
					{#if payee.note}<span data-slot="note">{payee.note}</span>{/if}
				</span>
			</div>
			<div class="flex shrink-0 items-center gap-0.5 text-muted-foreground">
				<Button
					variant="ghost"
					size="icon-xs"
					aria-label={`Edit ${payee.name}`}
					title="Edit name and note"
					onclick={start}
				>
					<PencilIcon aria-hidden="true" />
				</Button>
				<Button
					variant="ghost"
					size="icon-xs"
					aria-label={`Merge ${payee.name} into another payee`}
					title="Merge…"
					onclick={() => store.merge.start(payee.id)}
				>
					<GitMergeIcon aria-hidden="true" />
				</Button>
				<Button
					variant="ghost"
					size="icon-xs"
					aria-label={`Delete ${payee.name}`}
					title="Delete…"
					onclick={() => void store.remove.start(payee.id)}
				>
					<Trash2Icon aria-hidden="true" />
				</Button>
			</div>
		{/if}
	</div>
</li>
