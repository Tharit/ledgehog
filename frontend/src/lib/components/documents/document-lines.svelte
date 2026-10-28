<script lang="ts">
	import Card from '#lib/components/common/card.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import { amountHeader, columnCurrency } from '#lib/format/index.js';
	import type { DocumentDetail } from '#lib/types/domain.js';

	// The lines of a document as a table in a flush card: description, quantity, amount.
	let {
		lines,
		locale = 'en'
	}: {
		lines: DocumentDetail['lines'];
		locale?: string;
	} = $props();

	// a document has one currency: it heads the column and the cells show none (patterns §2)
	const currency = $derived(columnCurrency(lines.map((l) => l.amount.currency)));
</script>

<Card variant="flush" data-slot="document-lines">
	<div class="overflow-x-auto">
		<table class="w-full min-w-md text-[13px]">
			<thead>
				<tr class="h-8 border-b border-border bg-muted text-xs font-medium text-muted-foreground">
					<th scope="col" class="px-3 text-left font-medium">Description</th>
					<th scope="col" class="w-20 px-3 text-right font-medium">Qty</th>
					<th scope="col" class="w-32 px-3 text-right font-medium"
						>{amountHeader('Amount', currency)}</th
					>
				</tr>
			</thead>
			<tbody>
				{#each lines as line (line.line_no)}
					<tr class="h-8 border-b border-border last:border-b-0">
						<td class="px-3">{line.description}</td>
						<td class="px-3 text-right tabular-nums">{line.qty ?? ''}</td>
						<td class="px-3">
							<MoneyDisplay
								minor={line.amount.amount}
								currency={line.amount.currency}
								{locale}
								showCurrency={currency === null}
							/>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</Card>
