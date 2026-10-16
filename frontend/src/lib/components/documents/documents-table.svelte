<script lang="ts">
	import ActionButton from '#lib/components/common/action-button.svelte';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import { formatCount } from '#lib/format/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import type { DocumentRow } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';
	import CarrierLink from './carrier-link.svelte';
	import { DOCUMENT_COLUMNS, DOCUMENT_GRID_TEMPLATE } from './columns.js';
	import { describeDocumentError, documentTitle } from './describe.js';

	// The list of documents in the shape of the ledger table (patterns §4, §7): a snapshot that
	// shows what it was given. A row opens the document's page; its carrying transaction opens the
	// review panel.
	let {
		documents,
		total,
		status,
		loadingMore = false,
		error = null,
		moreError = null,
		lookups,
		locale = 'en',
		activeFilters = [],
		onopen,
		onopencarrier,
		onclearfilters,
		onretry,
		onloadmore
	}: {
		documents: readonly DocumentRow[];
		total: number;
		status: 'loading' | 'ready' | 'error';
		loadingMore?: boolean;
		error?: { code: string; message: string } | null;
		moreError?: { code: string; message: string } | null;
		lookups: Lookups;
		locale?: string;
		/** labels of the active filters, for the "nothing matches" state */
		activeFilters?: readonly string[];
		/** a row was chosen: show the document */
		onopen: (id: number) => void;
		/** the carrying transaction was chosen: open it in the review panel */
		onopencarrier: (entryId: number, origin: HTMLElement) => void;
		onclearfilters?: () => void;
		onretry?: () => void;
		onloadmore?: () => void | Promise<void>;
	} = $props();

	// the currency is written where amounts of several currencies are listed together (patterns §2)
	const showCurrency = $derived(new Set(documents.map((d) => d.total.currency)).size > 1);
	const failure = $derived(error ? describeDocumentError(error.code, 'documents') : null);
	const moreFailure = $derived(
		moreError ? describeDocumentError(moreError.code, 'documents') : null
	);

	function rowClick(event: MouseEvent, id: number) {
		// links and buttons inside the row do their own thing
		if (event.target instanceof Element && event.target.closest('a, button')) return;
		onopen(id);
	}
</script>

<section aria-label="Documents" class="relative">
	{#if status === 'error' && documents.length === 0 && failure}
		<ErrorState
			title={failure.title}
			message={failure.message}
			onretry={failure.retryable ? onretry : undefined}
			class="max-w-none items-center p-8 text-center"
		/>
	{:else if status === 'ready' && documents.length === 0}
		{#if activeFilters.length > 0}
			<EmptyState
				title="No documents match these filters"
				actionLabel="Clear filters"
				onaction={onclearfilters}
			>
				{activeFilters.join(' · ')}
			</EmptyState>
		{:else}
			<EmptyState title="No documents yet">
				Documents arrive with an importer that delivers them, such as an order history or a payment
				provider's export. A payee names its provider under Settings, then its transactions are
				matched to the documents.
			</EmptyState>
		{/if}
	{:else}
		<div role="grid" aria-label="Documents" aria-busy={status === 'loading'}>
			<div
				role="row"
				class="sticky top-0 z-10 grid h-8 items-center gap-x-3 border-b border-border bg-muted px-3 text-xs font-medium text-muted-foreground"
				style:grid-template-columns={DOCUMENT_GRID_TEMPLATE}
			>
				{#each DOCUMENT_COLUMNS as column (column.id)}
					<div role="columnheader" class={column.align === 'right' ? 'text-right' : undefined}>
						{column.header}
					</div>
				{/each}
			</div>

			{#if status === 'loading'}
				{#each Array.from({ length: 8 }, (_, n) => n) as i (i)}
					<div
						role="row"
						class="grid h-8 items-center gap-x-3 border-b border-border px-3"
						style:grid-template-columns={DOCUMENT_GRID_TEMPLATE}
						data-skeleton
					>
						{#each DOCUMENT_COLUMNS as column (column.id)}
							<div role="gridcell">
								{#if column.id === 'amount'}
									<div class="ml-auto h-3 w-14 animate-pulse rounded bg-muted"></div>
								{:else}
									<div
										class="h-3 animate-pulse rounded bg-muted"
										style:width={column.id === 'title' ? `${55 + ((i * 17) % 40)}%` : '66%'}
									></div>
								{/if}
							</div>
						{/each}
					</div>
				{/each}
			{:else}
				{#each documents as document (document.id)}
					<!-- the link in the title cell is the keyboard path; a click anywhere else opens too -->
					<!-- svelte-ignore a11y_click_events_have_key_events, a11y_interactive_supports_focus -->
					<div
						role="row"
						data-document-id={document.id}
						class={cn(
							'grid h-8 items-center gap-x-3 border-b border-border px-3 text-[13px] hover:bg-muted'
						)}
						style:grid-template-columns={DOCUMENT_GRID_TEMPLATE}
						onclick={(event) => rowClick(event, document.id)}
					>
						<div role="gridcell" class="truncate">{document.provider}</div>
						<div role="gridcell"><DateDisplay date={document.occurred_on} {locale} /></div>
						<div role="gridcell" class="min-w-0">
							<a
								href={`/documents/${document.id}`}
								class="block truncate rounded-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
							>
								{documentTitle(document)}
							</a>
						</div>
						<div role="gridcell">
							<MoneyDisplay
								minor={document.total.amount}
								currency={document.total.currency}
								{locale}
								{showCurrency}
							/>
						</div>
						<div role="gridcell" class="min-w-0">
							{#if document.carrier}
								<CarrierLink carrier={document.carrier} {lookups} {locale} onopen={onopencarrier} />
							{:else}
								<span class="text-muted-foreground">Not linked</span>
							{/if}
						</div>
					</div>
				{/each}
			{/if}
		</div>

		{#if status === 'ready'}
			<div class="flex flex-wrap items-center gap-3 py-3 text-xs text-muted-foreground">
				<span>{formatCount(documents.length, locale)} of {formatCount(total, locale)}</span>
				{#if documents.length < total}
					<ActionButton
						variant="outline"
						onclick={onloadmore}
						busy={loadingMore}
						busyLabel="Loading…"
					>
						Load more
					</ActionButton>
				{/if}
				{#if moreFailure}
					<Notice role="alert">
						{moreFailure.title}.
						{#snippet action()}
							{#if moreFailure.retryable}
								<ActionButton variant="link" class="h-auto p-0" onclick={onloadmore}>
									Try again
								</ActionButton>
							{/if}
						{/snippet}
					</Notice>
				{/if}
			</div>
		{/if}
	{/if}
</section>
