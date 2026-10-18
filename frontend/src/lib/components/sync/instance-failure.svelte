<script lang="ts">
	import ActionButton from '#lib/components/common/action-button.svelte';
	import { instanceUrl } from '#lib/importers/links.js';

	// What follows the failure of a login (ux/views/sync.md "Progress and report"; patterns §8): the
	// server's message once, muted, and a next step that routes on whether trying again can help and
	// on nothing else. One that can offers "Run again", which fetches the login's unfinished items and
	// asks for the PIN afresh; one that cannot says that trying again will not help yet, with a link to
	// the instance, where the importer's settings are. No message is read here.
	let {
		instanceId,
		message = null,
		stuck = false,
		canRunAgain = false,
		onrunagain
	}: {
		instanceId: number;
		/** the login's own error (a failed sign-in or an early end); an item's error is on its row */
		message?: string | null;
		/** a failure of this login that trying again cannot help */
		stuck?: boolean;
		/** a failure that trying again can help, and the sync is over, so a run can start */
		canRunAgain?: boolean;
		onrunagain?: () => void;
	} = $props();
</script>

<div class="flex flex-col items-start gap-1.5 pt-1 text-sm" data-slot="instance-failure">
	{#if message}
		<p class="text-muted-foreground" data-slot="instance-error">{message}</p>
	{/if}
	{#if stuck}
		<p class="text-muted-foreground" data-slot="run-fix">
			Trying again will not help yet. Fix what the error says, then fetch again.
			<a
				href={instanceUrl(instanceId)}
				class="text-foreground underline underline-offset-2 hover:no-underline"
				>Open the login's settings</a
			>
		</p>
	{/if}
	{#if canRunAgain}
		<ActionButton variant="outline" onclick={onrunagain}>Run again</ActionButton>
	{/if}
</div>
