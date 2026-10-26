<script lang="ts">
	import type { PayeesStore } from '#lib/payees/store.svelte.js';
	import { payeeMergeSummary } from '#lib/payees/summary.js';
	import { resolvePayee } from '#lib/theme/resolve.js';
	import MergeDialog from './merge-dialog.svelte';
	import type { PickerItem } from '#lib/components/common/picker.svelte';

	// Merge a payee into another (spec §3.6): entries and rules are repointed, the target's
	// attributes win. Every other payee is offered; the server decides the rest.
	let { store }: { store: PayeesStore } = $props();

	const source = $derived(
		store.merge.sourceId === null ? undefined : store.byId.get(store.merge.sourceId)
	);
	const items = $derived<PickerItem[]>(
		store.payees
			.filter((p) => p.id !== source?.id)
			.map((p) => {
				const look = resolvePayee(p);
				return {
					id: p.id,
					label: p.name,
					icon: look.icon,
					color: look.color,
					initial: look.initial
				};
			})
	);
</script>

<MergeDialog
	flow={store.merge}
	title={`Merge ${source?.name ?? 'payee'} into…`}
	description="Its entries and rules move to the target and it is deleted. Nothing returns to review."
	{items}
	label="payees"
>
	{#snippet summary(out)}
		{@const text = payeeMergeSummary(out)}
		<p class="font-medium">{text.totals}</p>
		{#if text.rules.length > 0}
			<ul class="flex list-disc flex-col gap-0.5 pl-5" aria-label="Rules">
				{#each text.rules as line (line)}
					<li>{line}</li>
				{/each}
			</ul>
		{/if}
		{#each text.notes as note (note)}
			<p class="text-muted-foreground">{note}</p>
		{/each}
	{/snippet}
</MergeDialog>
