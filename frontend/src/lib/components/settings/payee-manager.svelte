<script lang="ts">
	import { onMount } from 'svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { describeFailure } from '#lib/dimensions/errors.js';
	import type { PayeesStore } from '#lib/payees/store.svelte.js';
	import PayeeDeleteDialog from './payee-delete-dialog.svelte';
	import PayeeMergeDialog from './payee-merge-dialog.svelte';
	import PayeeRow from './payee-row.svelte';

	// The payees screen (spec §3.6): a curated list. A payee exists because someone wants to report
	// on that merchant, so nothing here creates one from a counterparty. Deleting and merging are
	// previewed first (patterns §6).
	let { store }: { store: PayeesStore } = $props();

	onMount(() => void store.load());

	let adding = $state(false);
	let name = $state('');
	let note = $state('');
	let addError = $state<string | null>(null);
	let busy = $state(false);
	let query = $state('');

	const needle = $derived(query.trim().toLowerCase());
	const shown = $derived(
		needle === '' ? store.payees : store.payees.filter((p) => p.name.toLowerCase().includes(needle))
	);

	async function add() {
		const trimmed = name.trim();
		if (trimmed === '') return;
		busy = true;
		const result = await store.create(trimmed, note.trim() === '' ? null : note.trim());
		busy = false;
		if (result.ok) {
			adding = false;
			name = '';
			note = '';
			addError = null;
		} else {
			addError = describeFailure(result.failure, 'payee', trimmed);
		}
	}
</script>

<div class="flex flex-col gap-4">
	<div class="flex items-start justify-between gap-4">
		<div class="flex flex-col gap-1">
			<h2 class="text-base font-semibold">Payees</h2>
			<p class="max-w-prose text-sm text-muted-foreground">
				Create a payee only for a merchant you want to report on. Most counterparties never need
				one.
			</p>
		</div>
		<Button
			size="sm"
			disabled={store.status !== 'ready'}
			onclick={() => {
				addError = null;
				adding = !adding;
			}}
		>
			Add payee
		</Button>
	</div>

	{#if adding}
		<form
			class="flex flex-wrap items-start gap-2 rounded-lg border border-border bg-card p-3"
			aria-label="New payee"
			onsubmit={(event) => {
				event.preventDefault();
				void add();
			}}
		>
			<div class="flex flex-col gap-1">
				<Input
					bind:value={name}
					placeholder="Payee name"
					aria-label="Name of the new payee"
					aria-invalid={addError !== null}
					disabled={busy}
					class="w-64"
				/>
				{#if addError}
					<span role="alert" class="text-xs text-destructive">{addError}</span>
				{/if}
			</div>
			<Input
				bind:value={note}
				placeholder="Note (optional)"
				aria-label="Note on the new payee"
				disabled={busy}
				class="w-64"
			/>
			<Button type="submit" size="sm" disabled={busy || name.trim() === ''}>Create</Button>
			<Button variant="ghost" size="sm" onclick={() => (adding = false)}>Cancel</Button>
		</form>
	{/if}

	<div class="flex min-h-5 flex-col gap-1">
		{#if store.notice}
			<Notice role={store.notice.error ? 'alert' : 'status'}>{store.notice.text}</Notice>
		{/if}
	</div>

	{#if store.status === 'loading'}
		<p class="text-sm text-muted-foreground" aria-busy="true">Loading payees…</p>
	{:else if store.status === 'error' && store.error}
		<ErrorState
			title="The payees could not be loaded"
			message={store.error.message}
			onretry={() => store.load()}
		/>
	{:else if store.payees.length === 0}
		<div class="rounded-lg border border-dashed border-border p-6 text-sm" data-slot="empty">
			<p class="font-medium">No payees yet</p>
			<p class="mt-1 max-w-prose text-muted-foreground">
				A payee groups the entries of one merchant so you can report on it, whatever the category.
				Add one with “Add payee” when there is a merchant you want to follow; rules can then set it
				on matching entries.
			</p>
		</div>
	{:else}
		{#if store.payees.length > 8}
			<Input
				type="search"
				placeholder="Filter payees…"
				aria-label="Filter payees"
				bind:value={query}
				class="max-w-xs"
			/>
		{/if}
		<ul aria-label="Payees">
			{#each shown as payee (payee.id)}
				<PayeeRow {payee} {store} />
			{:else}
				<li class="py-2 text-sm text-muted-foreground">No payee matches.</li>
			{/each}
		</ul>
	{/if}
</div>

<PayeeMergeDialog {store} />
<PayeeDeleteDialog {store} />
