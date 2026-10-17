<script lang="ts">
	import { page } from '$app/state';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import UploadPage from '#lib/components/importers/upload-page.svelte';
	import { positiveId } from '#lib/importers/links.js';

	// `/accounts/[id]/upload?instance=`: the account and the file importer's instance to upload with.
	// Both are in the address, so the page is the same after a reload; another pair, a new page.
	const accountId = $derived(positiveId(page.params.id));
	const instanceId = $derived(positiveId(page.url.searchParams.get('instance')));
</script>

<svelte:head>
	<title>Upload a file · Ledgehog</title>
</svelte:head>

{#if accountId === null}
	<ErrorState title="This is not an account" message="The address does not name an account." />
{:else if instanceId === null}
	<ErrorState
		title="No importer chosen"
		message="Start an upload from “Upload file” on one of the account’s sources."
	/>
	<ActionButton variant="outline" href={`/accounts/${accountId}`} class="mt-4 w-fit">
		Back to the account
	</ActionButton>
{:else}
	{#key `${accountId}:${instanceId}`}
		<UploadPage {accountId} {instanceId} />
	{/key}
{/if}
