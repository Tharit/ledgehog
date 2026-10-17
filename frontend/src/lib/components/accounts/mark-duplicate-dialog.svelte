<script lang="ts">
	import { untrack } from 'svelte';
	import {
		DuplicateFlow,
		type Direction,
		type MarkResult
	} from '#lib/accounts/duplicate-flow.svelte.js';
	import { isNewer } from '#lib/accounts/duplicate.js';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import { formatDate, formatMoney } from '#lib/format/index.js';
	import type { Provenance, StatementSource } from '#lib/types/domain.js';
	import DuplicateConsequences from './duplicate-consequences.svelte';

	// "Mark as duplicate of…" (spec §5.6, ux/views/account.md): a decision dialog that replaces the
	// row's detail. It lists the account's other imported rows of the same amount that are not
	// duplicates, nearest date first, to pick the original from. A pick previews both directions as
	// consequence lists, the newer row preselected as the duplicate, so the user marks the one that
	// loses less. Enter never confirms (patterns §11.2).
	let {
		open,
		row,
		flow = new DuplicateFlow(),
		locale = 'en',
		onclose,
		onmarked
	}: {
		open: boolean;
		/** the row whose detail was open */
		row: Provenance | null;
		flow?: DuplicateFlow;
		locale?: string;
		onclose: () => void;
		/** the row marked, the row it duplicates, and what the call touched */
		onmarked: (result: MarkResult) => void;
	} = $props();

	$effect(() => {
		if (!open || !row) {
			untrack(() => flow.stop());
			return;
		}
		untrack(() => void flow.start(row));
		return () => flow.stop();
	});

	async function confirm() {
		const result = await flow.confirm();
		if (result) onmarked(result);
	}

	const money = (m: { amount: number; currency: string }) =>
		formatMoney(m.amount, m.currency, { locale });
	const describe = (
		c: Pick<StatementSource, 'booked_on' | 'amount' | 'counterparty_name' | 'purpose'>
	) =>
		[formatDate(c.booked_on, locale), money(c.amount), c.counterparty_name ?? c.purpose ?? null]
			.filter(Boolean)
			.join(' · ');

	const feedback = $derived<DialogFeedback | null>(
		flow.failure ? { kind: flow.failure.kind, text: flow.failure.text } : null
	);

	const options = $derived.by(() => {
		const picked = flow.picked;
		if (!row || !picked) return [];
		const thisNewer = isNewer({ id: row.id, booked_on: row.booked_on }, picked);
		const mine = describe(row);
		const theirs = describe(picked);
		return [
			{
				direction: 'this' as Direction,
				title: `Mark this row as the duplicate (${mine})`,
				hint: thisNewer ? 'the newer row' : null
			},
			{
				direction: 'other' as Direction,
				title: `Mark the other row as the duplicate (${theirs})`,
				hint: thisNewer ? null : 'the newer row'
			}
		];
	});
</script>

<ActionDialog
	{open}
	{onclose}
	mode="decision"
	title="Mark as duplicate of…"
	description="Pick the row this one repeats. A duplicate counts toward no balance and has no entry."
	verb="Mark as duplicate"
	busyVerb="Marking…"
	busy={flow.busy}
	disabled={!flow.canConfirm}
	onsubmit={confirm}
	{feedback}
	width="lg"
>
	{#if flow.candidatesStatus === 'loading'}
		<p class="text-muted-foreground">Looking for rows of the same amount…</p>
	{:else if flow.candidatesStatus === 'error'}
		<p class="text-destructive" role="alert">
			The other rows could not be loaded. Close this and try again.
		</p>
	{:else if flow.candidates.length === 0}
		<p data-slot="no-candidates">
			No other imported row of this account has the same amount and is not a duplicate already.
		</p>
	{:else}
		<fieldset class="flex min-w-0 flex-col gap-1" data-slot="candidates">
			<legend class="mb-1 font-medium">The original</legend>
			{#each flow.candidates as candidate (candidate.id)}
				<label class="flex min-w-0 items-center gap-2 rounded-md px-1 py-0.5 hover:bg-muted">
					<input
						class="shrink-0"
						type="radio"
						name="original"
						value={candidate.id}
						checked={flow.pickedId === candidate.id}
						disabled={flow.busy}
						onchange={() => void flow.pick(candidate.id)}
					/>
					<span class="min-w-0 truncate" title={describe(candidate)}>{describe(candidate)}</span>
				</label>
			{/each}
		</fieldset>

		{#if flow.picked && flow.previews}
			{@const previews = flow.previews}
			<fieldset class="flex min-w-0 flex-col gap-2" data-slot="directions">
				<legend class="mb-1 font-medium">Which one is the duplicate?</legend>
				{#each options as option (option.direction)}
					<div class="flex min-w-0 flex-col gap-1 rounded-lg border border-border p-2">
						<label class="flex min-w-0 items-start gap-2">
							<input
								class="mt-0.5 shrink-0"
								type="radio"
								name="direction"
								value={option.direction}
								checked={flow.direction === option.direction}
								disabled={flow.busy}
								onchange={() => flow.choose(option.direction)}
							/>
							<span class="min-w-0 break-words">
								{option.title}{#if option.hint}
									<span class="text-muted-foreground"> · {option.hint}</span>{/if}
							</span>
						</label>
						<div class="min-w-0 pl-6">
							<DuplicateConsequences preview={previews[option.direction]} {locale} />
						</div>
					</div>
				{/each}
			</fieldset>
		{/if}
	{/if}
</ActionDialog>
