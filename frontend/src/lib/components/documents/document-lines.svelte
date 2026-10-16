<script lang="ts">
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import type { DocumentDetail } from '#lib/types/domain.js';

	// The lines of a document as a table: description, quantity, amount. The documents page shows
	// it whole; the review panel shows it under the document field, with the entry's own line marked.
	let {
		lines,
		locale = 'en',
		current = null
	}: {
		lines: DocumentDetail['lines'];
		locale?: string;
		/** the number of the line to mark (the entry's own) */
		current?: number | null;
	} = $props();
</script>

<div class="overflow-x-auto" data-slot="document-lines">
	<table class="w-full min-w-md text-[13px]">
		<thead>
			<tr class="h-8 border-b border-border bg-muted text-xs font-medium text-muted-foreground">
				<th scope="col" class="px-3 text-left font-medium">Description</th>
				<th scope="col" class="w-20 px-3 text-right font-medium">Qty</th>
				<th scope="col" class="w-32 px-3 text-right font-medium">Amount</th>
			</tr>
		</thead>
		<tbody>
			{#each lines as line (line.line_no)}
				<tr
					class={['h-8 border-b border-border', line.line_no === current && 'bg-accent']}
					aria-current={line.line_no === current ? 'true' : undefined}
				>
					<td class="px-3">{line.description}</td>
					<td class="px-3 text-right tabular-nums">{line.qty ?? ''}</td>
					<td class="px-3">
						<MoneyDisplay minor={line.amount.amount} currency={line.amount.currency} {locale} />
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>
