<script lang="ts">
	import { duplicateLabel } from '#lib/accounts/statement.js';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import { formatDate, formatInstant } from '#lib/format/index.js';
	import type { Provenance } from '#lib/types/domain.js';

	// The provenance widget (patterns §4.5, read-only): the normalised columns of a source
	// transaction, what the source said (`raw`), and the run it arrived in, or "entered by hand". A
	// duplicate names the row it duplicates, which opens. The raw source is shown as the importer
	// stored it; an importer-specific widget (spec §3.1) is a later refinement.
	let {
		provenance,
		locale = 'en',
		timeZone = 'UTC',
		onopenoriginal
	}: {
		provenance: Provenance;
		locale?: string;
		timeZone?: string;
		onopenoriginal?: (sourceId: number) => void;
	} = $props();

	function present(rows: [string, string | null | undefined][]): [string, string][] {
		return rows.filter(
			(row): row is [string, string] => row[1] !== null && row[1] !== undefined && row[1] !== ''
		);
	}

	const fields = $derived(
		present([
			['Counterparty', provenance.counterparty_name],
			['Counterparty reference', provenance.counterparty_ref],
			['Counterparty BIC', provenance.counterparty_bic],
			['Purpose', provenance.purpose],
			['Booking text', provenance.booking_text],
			['End-to-end id', provenance.end_to_end_id],
			['Mandate reference', provenance.mandate_ref]
		])
	);
	const run = $derived(provenance.run);
	const raw = $derived(
		provenance.raw === null || provenance.raw === undefined
			? null
			: JSON.stringify(provenance.raw, null, 2)
	);
</script>

<section aria-label="Provenance" class="flex flex-col gap-3 text-[13px]" data-slot="provenance">
	<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 rounded-lg bg-muted px-4 py-3">
		<dt class="text-muted-foreground">Booked on</dt>
		<dd>{formatDate(provenance.booked_on, locale)}</dd>
		{#if provenance.value_on}
			<dt class="text-muted-foreground">Value date</dt>
			<dd>{formatDate(provenance.value_on, locale)}</dd>
		{/if}
		<dt class="text-muted-foreground">Amount</dt>
		<dd>
			<MoneyDisplay
				minor={provenance.amount.amount}
				currency={provenance.amount.currency}
				{locale}
				showCurrency
				class="inline"
			/>
		</dd>
		{#if provenance.instructed_amount}
			<dt class="text-muted-foreground">Instructed amount</dt>
			<dd>
				<MoneyDisplay
					minor={provenance.instructed_amount.amount}
					currency={provenance.instructed_amount.currency}
					{locale}
					showCurrency
					class="inline"
				/>
			</dd>
		{/if}
		{#each fields as [label, value] (label)}
			<dt class="text-muted-foreground">{label}</dt>
			<dd class="min-w-0 break-words">{value}</dd>
		{/each}
	</dl>

	<p data-slot="provenance-origin">
		{#if provenance.authored || !run}
			<span class="text-muted-foreground">Entered by hand</span>
		{:else}
			<span class="text-muted-foreground">Arrived in a run of</span>
			{run.importer}{#if run.instance_label}
				({run.instance_label}){/if}
			<span class="text-muted-foreground">on</span>
			{formatInstant(run.started_at, timeZone, locale)}
		{/if}
	</p>

	{#if provenance.duplicate_of}
		{@const original = provenance.duplicate_of}
		<p data-slot="provenance-duplicate">
			This row is a
			<ActionButton variant="link" class="h-auto p-0" onclick={() => onopenoriginal?.(original.id)}>
				{duplicateLabel(original, locale)}
			</ActionButton>
			and counts toward no balance.
		</p>
	{/if}

	{#if raw !== null && !provenance.authored}
		<details class="rounded-lg border border-border px-3 py-2" data-slot="provenance-raw">
			<summary class="cursor-default text-muted-foreground">What the source said</summary>
			<pre class="mt-2 max-h-64 overflow-auto text-xs break-words whitespace-pre-wrap">{raw}</pre>
		</details>
	{/if}
</section>
