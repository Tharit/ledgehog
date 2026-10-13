<script lang="ts">
	import type { Snippet } from 'svelte';
	import Notice from './notice.svelte';

	// The reserved line under a page header or filter bar where its one notice appears, so the
	// content below does not jump when it does (patterns §11.5). A failure is an alert, anything
	// else a status; `action` is the notice's optional "Try again".
	let {
		notice,
		action
	}: { notice: { text: string; error: boolean } | null | undefined; action?: Snippet } = $props();
</script>

<div class="flex min-h-5 flex-col gap-1" data-slot="notice-line">
	{#if notice}
		<Notice role={notice.error ? 'alert' : 'status'} {action}>{notice.text}</Notice>
	{/if}
</div>
