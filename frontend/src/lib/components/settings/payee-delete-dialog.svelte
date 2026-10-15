<script lang="ts">
	import type { PayeesStore } from '#lib/payees/store.svelte.js';
	import { payeeDeleteSummary } from '#lib/payees/summary.js';
	import DeleteDialog from './delete-dialog.svelte';

	// Delete a payee (spec §3.6): only while no entry references it. It takes the rules that set it with
	// it and leaves the ones that only test it (they stop matching): the preview lists both.
	// Referenced, it is merged instead.
	let { store }: { store: PayeesStore } = $props();

	const name = $derived(
		store.remove.id === null ? 'payee' : (store.byId.get(store.remove.id)?.name ?? 'payee')
	);
</script>

<DeleteDialog
	flow={store.remove}
	title={`Delete ${name}?`}
	onmerge={() => {
		const id = store.remove.id;
		store.remove.close();
		if (id !== null) store.merge.start(id);
	}}
>
	{#snippet body(out)}
		{@const text = payeeDeleteSummary(out)}
		{#if !text.deletable}
			<p>{text.reason}</p>
		{:else}
			{#if !text.deleted && !text.dangling}
				<p>No entry and no rule uses {out.payee.name}.</p>
			{:else}
				<p>No entry uses {out.payee.name}.</p>
			{/if}
			{#each [text.deleted, text.dangling] as part, i (i)}
				{#if part}
					<p>{part.heading} {part.names.join(', ')}</p>
				{/if}
			{/each}
		{/if}
	{/snippet}
</DeleteDialog>
