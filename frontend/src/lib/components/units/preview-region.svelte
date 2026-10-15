<script lang="ts">
	import ActionButton from '#lib/components/common/action-button.svelte';
	import EntryRow from '#lib/components/ledger/entry-row.svelte';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { differenceOf } from '#lib/units/problems.js';
	import type { UnitDraftFlow } from '#lib/units/unit-draft-flow.svelte.js';
	import { consequenceGroups, previewRowEntry, resultText } from '#lib/units/view.js';
	import { cn } from '#lib/utils.js';

	// What committing the draft would do (patterns §6): the state it leads to in plain words, the
	// problems that would refuse it, then the consequences grouped by effect, each a compact row
	// that can be opened. "Checking what would change…" while a preview is on its way; the last
	// answer stays, dimmed, so the region does not jump.
	let {
		flow,
		lookups,
		locale = 'en',
		onopen
	}: {
		flow: UnitDraftFlow;
		lookups: Lookups;
		locale?: string;
		/** open the unit of a consequence row (the panel asks first when the draft has changes) */
		onopen: (entryId: number) => void;
	} = $props();

	const preview = $derived(flow.preview);
	const checking = $derived(flow.previewStatus === 'loading' || flow.stale);
	const statusText = $derived(
		flow.previewStatus === 'error'
			? 'The preview could not be loaded.'
			: checking
				? 'Checking what would change…'
				: ''
	);
	const groups = $derived(consequenceGroups(preview));
	const problems = $derived(flow.problemTexts);
	const showCurrency = $derived(
		new Set(groups.flatMap((g) => g.items.map((c) => c.row.amount.currency))).size > 1
	);

	function baseOf(id: number) {
		return flow.unit?.entries.find((e) => e.id === id) ?? null;
	}
</script>

<section
	aria-label="Preview"
	class="flex flex-col gap-3 rounded-lg border bg-card p-4 text-[13px]"
	data-slot="preview-region"
>
	<!-- the status takes a row only while there is something to say; the live region stays -->
	<div class={statusText ? 'flex flex-wrap items-baseline gap-x-3' : 'contents'}>
		<p
			role="status"
			aria-live="polite"
			class={cn('text-muted-foreground', !statusText && 'sr-only')}
			data-slot="preview-status"
		>
			{statusText}
		</p>
		{#if flow.previewStatus === 'error'}
			<ActionButton variant="link" class="h-auto p-0" onclick={() => flow.retryPreview()}>
				Try again
			</ActionButton>
		{/if}
	</div>

	{#if preview}
		<p class={cn('text-sm', checking && 'opacity-60')} data-slot="preview-result">
			<span class="text-muted-foreground">After this commit: </span>
			<strong class="font-semibold">{resultText(preview.state)}</strong>
		</p>
	{/if}

	{#if problems.length > 0}
		<ul
			class={cn('flex flex-col gap-1.5', checking && 'opacity-60')}
			aria-label="Problems"
			data-slot="problems"
		>
			{#each problems as { problem, text }, i (i)}
				<li class="flex flex-wrap items-baseline gap-x-2 text-destructive" data-code={problem.code}>
					<span>{text.text}</span>
					{#if text.remedy}<span class="text-muted-foreground">{text.remedy}</span>{/if}
					{#if differenceOf(problem) !== null}
						<ActionButton
							variant="link"
							class="h-auto p-0"
							onclick={() => flow.splitOffDifference(problem)}
						>
							Split off the difference
						</ActionButton>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}

	{#each groups as group (group.kind)}
		<section
			aria-label={group.title}
			class={cn('flex flex-col gap-1', checking && 'opacity-60')}
			data-slot="consequences"
			data-kind={group.kind}
		>
			<h3 class="text-xs font-medium text-muted-foreground">
				{group.title} ({group.items.length})
			</h3>
			<div role="grid" aria-label={group.title}>
				{#each group.items as item (item.entry_id)}
					<EntryRow
						entry={previewRowEntry(item.row, baseOf(item.entry_id))}
						{lookups}
						{locale}
						{showCurrency}
						onopen={item.entry_id > 0 && item.kind !== 'deleted' && item.kind !== 'created'
							? () => onopen(item.entry_id)
							: undefined}
					/>
				{/each}
			</div>
		</section>
	{/each}
</section>
