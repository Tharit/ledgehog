<script lang="ts">
	import { untrack } from 'svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import { documentTitle } from '#lib/components/documents/describe.js';
	import * as Command from '#lib/components/ui/command/index.js';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import { formatDate, formatMoney } from '#lib/format/index.js';
	import DocumentLines from '#lib/components/documents/document-lines.svelte';
	import { DocumentFinder } from '#lib/stores/document-finder.svelte.js';
	import { DocumentDetailStore } from '#lib/stores/documents.svelte.js';
	import type { DocumentSummary } from '#lib/units/types.js';
	import type { UnitDraftFlow } from '#lib/units/unit-draft-flow.svelte.js';
	import { documentHints, waitingText } from '#lib/units/unit-document.js';
	import type { EntryView } from '#lib/units/view.js';
	import EvidenceLine from './evidence-line.svelte';

	// The document of a transaction (spec §5.8, §6; documents view, panel section): the document
	// it carries or would carry and how that came about, the documents suggested (offers in a
	// popover, nearest first, with what they have in common with the entry), finding one by hand,
	// "none of these", the wait, and the split along the lines. Every choice is a draft edit: the
	// link is written only by the commit. Where documents are suggested or awaited a commit needs a
	// decision, and "Commit without a document" is that decision, taken on purpose (patterns §6).
	let {
		view,
		flow,
		locale = 'en'
	}: {
		view: EntryView;
		flow: UnitDraftFlow;
		locale?: string;
	} = $props();

	// only called for an entry the preview or the draft has something to say about
	const doc = $derived(view.document!);
	const loading = $derived(flow.previewStatus === 'loading' || flow.stale);
	const entry = $derived.by(() => {
		const amount = view.sourceAmount ?? view.amount;
		return {
			amount: amount?.amount ?? 0,
			currency: amount?.currency ?? 'EUR',
			bookedOn: view.row?.booked_on ?? view.stored?.booked_on ?? null
		};
	});

	const finder = new DocumentFinder();
	let open = $state(false);
	let query = $state('');
	$effect(() => {
		const provider = doc.provider;
		if (!open || provider === null) return;
		const text = query;
		// the first look is at once, typing rests a moment
		untrack(() => finder.search(provider, text, text === ''));
	});
	$effect(() => {
		if (open) return;
		query = '';
		untrack(() => finder.dispose());
	});
	$effect(() => () => finder.dispose());

	// the lines of the document shown, fetched when the toggle opens and not before
	const detail = new DocumentDetailStore();
	let showLines = $state(false);
	const shownId = $derived(doc.document?.id ?? null);
	$effect(() => {
		const id = shownId;
		if (!showLines || id === null) return;
		untrack(() => {
			if (detail.document?.id !== id) void detail.load(id);
		});
	});
	$effect(() => () => detail.dispose());

	function searchText(document: DocumentSummary): string {
		return [
			document.provider,
			document.merchant_name,
			document.title,
			document.external_id,
			formatDate(document.occurred_on, locale),
			formatMoney(document.total.amount, document.total.currency, { locale })
		]
			.join(' ')
			.toLowerCase();
	}

	const needle = $derived(query.trim().toLowerCase());
	const suggested = $derived(
		needle === '' ? doc.suggestions : doc.suggestions.filter((d) => searchText(d).includes(needle))
	);
	// documents found by hand: the ones not already offered above, nor the one picked
	const found = $derived.by(() => {
		const offered = new Set([...doc.suggestions.map((d) => d.id), doc.document?.id]);
		return finder.documents.filter((d) => !offered.has(d.id));
	});

	function choose(document: DocumentSummary) {
		open = false;
		flow.pickDocument(view.id, { id: document.id, version: document.version });
	}

	function chooseNone() {
		open = false;
		flow.noDocument(view.id);
	}

	const pickedOrLinked = $derived(doc.state === 'picked' || doc.state === 'linked');
	// the split along the lines: proposed by the server, or the user's own choice
	const splitting = $derived(
		doc.split?.proposed === true || doc.edit?.mode === 'split_along_lines'
	);
	const offerSplit = $derived(
		doc.split !== null && doc.split.available && !splitting && doc.split.document !== null
	);
	const waitingLine = $derived(doc.state === 'open' && doc.waiting !== null);
	// the rest of an order is awaited beside the document the transaction carries
	const orderLine = $derived(doc.state === 'linked' && doc.waiting !== null);
</script>

{#snippet summaryLine(document: DocumentSummary)}
	<span class="flex flex-wrap items-center gap-x-2">
		<span>{document.provider}</span>
		<DateDisplay date={document.occurred_on} {locale} />
		<MoneyDisplay
			minor={document.total.amount}
			currency={document.total.currency}
			{locale}
			showCurrency
			class="inline"
		/>
		<span class="truncate">{documentTitle(document)}</span>
		{#if document.line_count > 1}
			<span class="text-xs text-muted-foreground">{document.line_count} lines</span>
		{/if}
	</span>
{/snippet}

{#snippet offer(document: DocumentSummary, hints: string[])}
	<Command.Item
		value={`document-${document.id}`}
		class="items-start"
		data-document={document.id}
		onSelect={() => choose(document)}
	>
		<span class="flex min-w-0 flex-1 flex-col gap-0.5">
			{@render summaryLine(document)}
			{#if hints.length > 0}
				<span class="text-xs text-muted-foreground" data-slot="document-hint">
					{hints.join(' · ')}
				</span>
			{/if}
		</span>
	</Command.Item>
{/snippet}

<dt class="pt-1.5 text-muted-foreground">Document</dt>
<dd class="flex min-w-0 flex-col gap-1" data-slot="document" data-state={doc.state}>
	{#if doc.state === 'none'}
		<p class="text-muted-foreground" data-slot="document-line">No document</p>
	{:else if doc.state === 'resolve_again'}
		<p class="text-muted-foreground" data-slot="document-line">Matched again when you commit</p>
	{:else if pickedOrLinked}
		{#if doc.document}
			<p data-slot="document-line">{@render summaryLine(doc.document)}</p>
		{:else}
			<p class="text-muted-foreground" data-slot="document-line">Checking the document…</p>
		{/if}
	{:else if waitingLine && doc.waiting}
		<p class="text-muted-foreground" data-slot="document-waiting">
			{waitingText(doc.waiting, locale)}
		</p>
	{:else if doc.suggestions.length > 0}
		<p class="text-muted-foreground italic" data-slot="document-line">
			{doc.suggestions.length === 1
				? '1 document is suggested'
				: `${doc.suggestions.length} documents are suggested`}
		</p>
	{:else}
		<p class="text-muted-foreground" data-slot="document-line">No document</p>
	{/if}
	{#if orderLine && doc.waiting}
		<p class="text-xs text-muted-foreground" data-slot="document-waiting">
			{waitingText(doc.waiting, locale)}
		</p>
	{/if}
	<EvidenceLine evidence={doc.evidence} />

	{#if doc.document}
		<div class="flex flex-col gap-1" data-slot="document-lines-region">
			<ActionButton
				variant="link"
				class="h-auto self-start p-0 text-xs"
				data-slot="toggle-lines"
				aria-expanded={showLines}
				onclick={() => (showLines = !showLines)}
			>
				{showLines ? 'Hide lines' : 'Show lines'}
			</ActionButton>
			{#if showLines}
				{#if detail.status === 'error'}
					<p class="text-xs text-muted-foreground" data-slot="document-lines-error">
						The lines could not be loaded.
					</p>
				{:else if detail.document && detail.document.id === shownId}
					{#if detail.document.lines.length === 0}
						<p class="text-xs text-muted-foreground">This document has no lines.</p>
					{:else}
						<DocumentLines
							lines={detail.document.lines}
							{locale}
							current={view.documentLine?.line_no ?? null}
						/>
					{/if}
				{:else}
					<p class="text-xs text-muted-foreground" role="status">Loading the lines…</p>
				{/if}
			{/if}
		</div>
	{/if}

	{#if doc.carriers.length > 0}
		<p class="text-xs text-muted-foreground" data-slot="document-carriers">
			Also carrying this document in this unit:
			{#each doc.carriers as carrier, i (carrier.entryId)}
				{i > 0 ? ', ' : ''}
				{#if carrier.bookedOn}<DateDisplay date={carrier.bookedOn} {locale} />{/if}
				{#if carrier.amount}
					<MoneyDisplay
						minor={carrier.amount.amount}
						currency={carrier.amount.currency}
						{locale}
						class="inline"
					/>
				{/if}
			{/each}
		</p>
	{/if}

	{#if doc.decisionRequired}
		<div class="flex flex-wrap items-center gap-x-3 gap-y-1" data-slot="document-decision">
			<p class="text-xs text-muted-foreground">
				Pick a document, or commit without one: a commit needs this decision.
			</p>
			<ActionButton
				variant="outline"
				data-slot="commit-without-document"
				disabled={flow.committing}
				onclick={chooseNone}
			>
				Commit without a document
			</ActionButton>
		</div>
	{/if}

	{#if splitting}
		<div
			class="flex flex-col gap-0.5"
			data-slot="document-split"
			data-proposed={doc.split?.proposed || undefined}
		>
			<p class="text-xs text-muted-foreground">
				{doc.edit?.mode === 'split_along_lines'
					? 'Split along the lines of the document, as you chose.'
					: 'Split along the lines of the document: one entry per line.'}
			</p>
			{#if doc.split?.replacesStoredSplit}
				<p class="text-xs text-muted-foreground" data-slot="document-split-replaces">
					This replaces the existing split: its other entries are deleted, with their tags.
				</p>
			{/if}
			<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
				{#if doc.splitEdited}
					<ActionButton
						variant="link"
						class="h-auto p-0 text-xs"
						data-slot="reset-split"
						disabled={flow.committing}
						onclick={() => flow.resetSplit(view.id)}
					>
						Reset split to proposal
					</ActionButton>
				{/if}
			</div>
		</div>
	{/if}

	{#if doc.unsplit}
		<p class="text-xs text-muted-foreground" data-slot="document-unsplit">
			Linked, not split along the lines: you removed the proposal.
		</p>
	{/if}

	<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
		<Popover.Root bind:open>
			<Popover.Trigger>
				{#snippet child({ props })}
					<ActionButton
						variant="outline"
						data-picker="document"
						disabled={flow.committing}
						{...props}
					>
						{pickedOrLinked ? 'Pick another document…' : 'Pick a document…'}
					</ActionButton>
				{/snippet}
			</Popover.Trigger>
			<Popover.Content
				align="start"
				class="w-[26rem] max-w-[90vw] gap-0 p-1"
				aria-label="Choose a document"
			>
				<Command.Root shouldFilter={false} aria-busy={loading || finder.status === 'loading'}>
					<Command.Input
						placeholder="Find a document…"
						aria-label="Search documents"
						bind:value={query}
					/>
					<Command.List aria-label="Documents" class="max-h-72">
						{#if suggested.length > 0}
							<Command.Group heading="Suggested" data-group="suggested">
								{#each suggested as document (document.id)}
									{@render offer(document, documentHints(document, entry, locale))}
								{/each}
							</Command.Group>
						{/if}
						{#if doc.provider !== null && found.length > 0}
							<Command.Group heading="Not fully charged" data-group="found">
								{#each found as document (document.id)}
									{@render offer(document, documentHints(document, entry, locale))}
								{/each}
							</Command.Group>
						{/if}
						<Command.Group data-group="none">
							<Command.Item value="document-none" data-document="none" onSelect={chooseNone}>
								None of these
							</Command.Item>
						</Command.Group>
						{#if doc.provider === null}
							<p
								class="px-2 py-3 text-center text-xs text-muted-foreground"
								data-slot="document-no-provider"
							>
								Set a document provider on the payee to find documents by hand.
							</p>
						{:else if finder.status === 'error'}
							<p
								class="px-2 py-3 text-center text-xs text-muted-foreground"
								data-slot="document-find-error"
							>
								The documents could not be loaded.
							</p>
						{:else if finder.status === 'ready' && found.length === 0 && suggested.length === 0}
							<p
								class="px-2 py-3 text-center text-xs text-muted-foreground"
								data-slot="document-none-found"
							>
								No document of {doc.provider} that is not fully charged.
							</p>
						{/if}
					</Command.List>
				</Command.Root>
			</Popover.Content>
		</Popover.Root>
		{#if offerSplit && doc.split?.document}
			{@const along = doc.split.document}
			<ActionButton
				variant="outline"
				data-slot="split-along-lines"
				disabled={flow.committing}
				onclick={() => flow.splitAlongLines(view.id, along)}
			>
				Split along the lines
			</ActionButton>
		{/if}
		{#if doc.lookAgain}
			<ActionButton
				variant="link"
				class="h-auto p-0 text-xs"
				data-slot="resolve-again"
				disabled={flow.committing}
				onclick={() => flow.reresolveDocument(view.id)}
			>
				Look for a document
			</ActionButton>
		{/if}
		{#if doc.edit !== undefined || doc.unsplit}
			<ActionButton
				variant="link"
				class="h-auto p-0 text-xs"
				data-slot="reset-document"
				disabled={flow.committing}
				onclick={() => flow.resetDocument(view.id)}
			>
				Reset to proposal
			</ActionButton>
		{/if}
	</div>
	{#if doc.split?.replacesStoredSplit && offerSplit}
		<p class="text-xs text-muted-foreground" data-slot="document-split-hint">
			Splitting along the lines replaces the existing split: the entries it deletes are listed under
			Deleted.
		</p>
	{/if}
</dd>
