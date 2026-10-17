<script lang="ts">
	import ActionButton from '#lib/components/common/action-button.svelte';
	import { instanceUrl, uploadUrl } from '#lib/importers/links.js';
	import type { ImportRun } from '#lib/accounts/runs.js';

	// What follows the error of a failed run, in the account page's run row (patterns §8): a run that
	// trying again can help (the server says so, from the error's class: no message is read here)
	// offers "Upload file"; one that cannot says what to fix instead, with a link to the instance.
	// File importers only for now (fetch importers get theirs with the sync view). Nothing for a run
	// that is not failed, or whose instance was deleted.
	let {
		run,
		fileImporter = false
	}: {
		run: Pick<ImportRun, 'status' | 'retryable' | 'instance_id' | 'account_id'>;
		/** whether the run's importer takes a file (the catalog says) */
		fileImporter?: boolean;
	} = $props();

	const link = 'underline underline-offset-2 hover:no-underline';
	const instance = $derived(run.instance_id);
</script>

{#if run.status === 'failed' && instance !== null && fileImporter}
	{#if run.retryable}
		{#if run.account_id !== null}
			<ActionButton variant="outline" href={uploadUrl(run.account_id, instance)}
				>Upload file</ActionButton
			>
		{/if}
	{:else}
		<span class="text-muted-foreground" data-slot="run-fix">
			<a href={instanceUrl(instance)} class={link}>Fix the profile</a>, then upload again.
		</span>
	{/if}
{/if}
