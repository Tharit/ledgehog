<script lang="ts">
	import { page } from '$app/state';
	import ArrowLeftIcon from '@lucide/svelte/icons/arrow-left';
	import { onDestroy } from 'svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import DocumentDetailView from '#lib/components/documents/document-detail.svelte';
	import { describeDocumentError } from '#lib/components/documents/describe.js';
	import { DocumentDetailStore } from '#lib/stores/documents.svelte.js';

	const detail = new DocumentDetailStore();

	const documentId = $derived.by(() => {
		const id = Number(page.params.id);
		return Number.isSafeInteger(id) && id > 0 ? id : null;
	});

	$effect(() => {
		if (documentId !== null) void detail.load(documentId);
	});

	onDestroy(() => detail.dispose());

	const failure = $derived(
		detail.error ? describeDocumentError(detail.error.code, 'document') : null
	);
</script>

<svelte:head>
	<title>Document · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<a
		href="/documents"
		class="inline-flex w-fit items-center gap-1.5 rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
	>
		<ArrowLeftIcon size={14} strokeWidth={1.75} aria-hidden="true" />
		Documents
	</a>

	{#if documentId === null}
		<ErrorState title="This is not a document" message="The address does not name a document." />
	{:else if detail.status === 'error' && failure}
		<ErrorState
			title={failure.title}
			message={failure.message}
			onretry={failure.retryable ? () => detail.load(documentId) : undefined}
		/>
	{:else if detail.status === 'ready' && detail.document}
		<DocumentDetailView document={detail.document} locale={detail.locale} />
	{:else}
		<p class="text-sm text-muted-foreground" aria-busy="true">Loading…</p>
	{/if}
</div>
