<script lang="ts">
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import { formatDate } from '#lib/format/index.js';
	import type { DocumentDetail } from '#lib/types/domain.js';
	import { documentTitle } from './describe.js';
	import DocumentLines from './document-lines.svelte';

	// One document (view sketch: ux/views/documents.md): its merchant, total and lines, read-only.
	let {
		document,
		locale = 'en'
	}: {
		document: DocumentDetail;
		locale?: string;
	} = $props();
</script>

<div class="flex flex-col gap-6">
	<PageHeader
		level={1}
		title={documentTitle(document)}
		description={`${document.provider} · ${formatDate(document.occurred_on, locale)}`}
	/>

	<dl class="grid max-w-2xl grid-cols-[8rem_1fr] gap-x-4 gap-y-2 text-sm">
		<dt class="text-muted-foreground">Total</dt>
		<dd>
			<MoneyDisplay
				minor={document.total.amount}
				currency={document.total.currency}
				{locale}
				showCurrency
				class="inline"
			/>
		</dd>
		<dt class="text-muted-foreground">Reference</dt>
		<dd class="truncate">{document.external_id}</dd>
	</dl>

	<section aria-labelledby="document-lines" class="flex flex-col gap-2">
		<h2 id="document-lines" class="text-base font-semibold">Lines</h2>
		{#if document.lines.length === 0}
			<p class="text-sm text-muted-foreground">This document has no lines.</p>
		{:else}
			<DocumentLines lines={document.lines} {locale} />
		{/if}
	</section>
</div>
