<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import NoticeLine from '#lib/components/common/notice-line.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import type { PayeesStore } from '#lib/payees/store.svelte.js';
	import type { Payee } from '#lib/types/domain.js';
	import PayeeDeleteDialog from './payee-delete-dialog.svelte';
	import PayeeFormDialog from './payee-form-dialog.svelte';
	import PayeeMergeDialog from './payee-merge-dialog.svelte';
	import PayeeRow from './payee-row.svelte';

	// The payees screen (spec §3.6): a curated list. A payee exists because someone wants to report
	// on that merchant, so nothing here creates one from a counterparty. Adding and editing are a
	// form dialog; deleting and merging are previewed first (patterns §6, §11).
	let { store }: { store: PayeesStore } = $props();

	onMount(() => void store.load());

	let query = $state('');

	const needle = $derived(query.trim().toLowerCase());
	const shown = $derived(
		needle === '' ? store.payees : store.payees.filter((p) => p.name.toLowerCase().includes(needle))
	);

	// the form dialog adds (payee null) or edits; the payee stays while the dialog closes so that
	// its title does not change under the closing animation
	let formOpen = $state(false);
	let formPayee = $state<Payee | null>(null);

	function openForm(payee: Payee | null) {
		formPayee = payee;
		formOpen = true;
	}

	// a new payee is revealed (a filter that hides it is cleared), marked briefly and focused
	let revealedId = $state<number | null>(null);
	let focusRevealed = $state(false);
	let revealTimer: ReturnType<typeof setTimeout> | undefined;

	function saved(payee: Payee, added: boolean) {
		formOpen = false;
		if (!added) return;
		query = '';
		revealedId = payee.id;
		focusRevealed = false;
		clearTimeout(revealTimer);
		revealTimer = setTimeout(() => (revealedId = null), 2500);
	}
	onDestroy(() => clearTimeout(revealTimer));
</script>

<div class="flex flex-col gap-4">
	<PageHeader
		title="Payees"
		description="Add a payee only for a merchant you want to report on. Most counterparties never need one."
		actionLabel="Add payee"
		onaction={() => openForm(null)}
		actionDisabled={store.status !== 'ready'}
	/>

	<NoticeLine notice={store.notice} />

	{#if store.status === 'loading'}
		<div aria-busy="true" aria-label="Loading payees" data-slot="payees-loading">
			{#each [0, 1, 2, 3, 4] as i (i)}
				<div class="flex h-12 items-center gap-3 border-b border-border">
					<div class="size-8 shrink-0 animate-pulse rounded-full bg-muted"></div>
					<div
						class="h-3 animate-pulse rounded bg-muted"
						style:width={`${30 + ((i * 17) % 30)}%`}
					></div>
				</div>
			{/each}
		</div>
	{:else if store.status === 'error' && store.error}
		<ErrorState
			title="The payees could not be loaded"
			message={store.error.message}
			onretry={() => store.load()}
		/>
	{:else if store.payees.length === 0}
		<EmptyState title="No payees yet" actionLabel="Add payee" onaction={() => openForm(null)}>
			A payee groups the entries of one merchant so you can report on it, whatever the category. Add
			one when there is a merchant you want to follow; rules can then set it on matching entries.
		</EmptyState>
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
				<PayeeRow
					{payee}
					{store}
					revealed={payee.id === revealedId}
					focus={focusRevealed && payee.id === revealedId}
					onedit={() => openForm(payee)}
				/>
			{:else}
				<li class="py-2 text-sm text-muted-foreground">No payee matches.</li>
			{/each}
		</ul>
	{/if}
</div>

<PayeeFormDialog
	{store}
	open={formOpen}
	payee={formPayee}
	onclose={() => (formOpen = false)}
	onsaved={saved}
	onclosedafteradd={() => (focusRevealed = true)}
/>
<PayeeMergeDialog {store} />
<PayeeDeleteDialog {store} />
