<script lang="ts">
	import ActionButton from '#lib/components/common/action-button.svelte';
	import { instanceUrl, uploadUrl } from '#lib/importers/links.js';
	import type { ImportRun } from '#lib/accounts/runs.js';

	// What follows the error of a failed run, in the account page's run row (patterns §8): a run that
	// trying again can help (the server says so, from the error's class: no message is read here)
	// offers the importer's own action, "Upload file" for a file importer and "Run again", a one-item
	// sync, for one that fetches; one that cannot says what to fix instead, with a link to the instance.
	// Nothing for a run that is not failed, or whose instance was deleted.
	let {
		run,
		importerKind = null,
		onrunagain
	}: {
		run: Pick<ImportRun, 'status' | 'retryable' | 'instance_id' | 'account_id'>;
		/** what the importer of the run is, from the catalog; none known: no next step */
		importerKind?: 'file' | 'fetch' | null;
		/** "Run again" of a fetch run: the page starts the one-item sync */
		onrunagain?: () => void;
	} = $props();

	const link = 'underline underline-offset-2 hover:no-underline';
	const instance = $derived(run.instance_id);
</script>

{#if run.status === 'failed' && instance !== null && importerKind === 'file'}
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
{:else if run.status === 'failed' && instance !== null && importerKind === 'fetch'}
	{#if run.retryable}
		{#if run.account_id !== null}
			<ActionButton variant="outline" onclick={onrunagain}>Run again</ActionButton>
		{/if}
	{:else}
		<span class="text-muted-foreground" data-slot="run-fix">
			Trying again will not help yet. Fix what the error says, then fetch again.
			<a href={instanceUrl(instance)} class={link}>Open the login's settings</a>
		</span>
	{/if}
{/if}
