<script lang="ts">
	import ActionButton from '#lib/components/common/action-button.svelte';
	import { instanceUrl, uploadUrl } from '#lib/importers/links.js';
	import type { ImportRun } from '#lib/accounts/runs.js';

	// What follows the error of a failed run (patterns §8): a run that trying again can help (the
	// server says so, from the error's class: no message is read here) offers to run it again, which
	// for a file importer is "Upload file"; one that cannot says what to fix instead, with a link to
	// the instance. Nothing for a run that is not failed, or whose instance was deleted.
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

{#if run.status === 'failed' && instance !== null}
	{#if run.retryable}
		{#if fileImporter && run.account_id !== null}
			<ActionButton variant="outline" href={uploadUrl(run.account_id, instance)}
				>Upload file</ActionButton
			>
		{:else}
			<ActionButton variant="outline" href={instanceUrl(instance)}>Run again</ActionButton>
		{/if}
	{:else}
		<span class="text-muted-foreground" data-slot="run-fix">
			{#if fileImporter}
				<a href={instanceUrl(instance)} class={link}>Fix the profile</a>, then upload again.
			{:else}
				<a href={instanceUrl(instance)} class={link}>Fix the importer</a>, then run it again.
			{/if}
		</span>
	{/if}
{/if}
