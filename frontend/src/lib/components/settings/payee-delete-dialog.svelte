<script lang="ts">
	import type { PayeesStore } from '#lib/payees/store.svelte.js';
	import { payeeDeleteSummary } from '#lib/payees/summary.js';
	import DeleteDialog from './delete-dialog.svelte';

	// Delete a payee (spec §3.6): only while no entry references it, and it takes its rules with
	// it, which the preview lists. Referenced, it is merged instead.
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
		{:else if text.rules.length === 0}
			<p>No entry and no rule uses {out.payee.name}.</p>
		{:else}
			<p>No entry uses {out.payee.name}. These rules would be deleted with it:</p>
			<ul class="flex list-disc flex-col gap-0.5 pl-5" aria-label="Rules deleted">
				{#each text.rules as line, i (i)}
					<li>{line}</li>
				{/each}
			</ul>
		{/if}
	{/snippet}
</DeleteDialog>
