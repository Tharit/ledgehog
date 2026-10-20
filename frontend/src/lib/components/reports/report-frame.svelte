<script lang="ts" generics="T">
	import type { Snippet } from 'svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import { describeReportError } from '#lib/reports/errors.js';

	// What a report page shows around its data (patterns §7): the skeleton on the first load only, an
	// error that says what it is, and otherwise the data, which stays on screen while a new answer
	// is read.
	let {
		data,
		status,
		error,
		onretry,
		children
	}: {
		data: T | null;
		status: 'loading' | 'ready' | 'error';
		error: { code: string } | null;
		onretry?: () => void;
		children: Snippet<[T]>;
	} = $props();

	const failure = $derived(error ? describeReportError(error.code) : null);
</script>

{#if status === 'error' && failure}
	<ErrorState
		title={failure.title}
		message={failure.message}
		onretry={failure.retryable ? onretry : undefined}
		class="max-w-none items-center p-8 text-center"
	/>
{:else if data === null}
	<div class="flex flex-col gap-4" data-slot="report-skeleton" aria-busy="true">
		<div class="h-56 animate-pulse rounded-md bg-muted"></div>
		<div class="h-40 animate-pulse rounded-md bg-muted"></div>
	</div>
{:else}
	{@render children(data)}
{/if}
