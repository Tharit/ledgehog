<script lang="ts">
	import { page } from '$app/state';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import DiscoveryPage from '#lib/components/importers/discovery-page.svelte';
	import { positiveId } from '#lib/importers/links.js';

	const instanceId = $derived(positiveId(page.params.id));
</script>

<svelte:head>
	<title>Refresh accounts · Settings · Ledgehog</title>
</svelte:head>

{#if instanceId === null}
	<ErrorState title="This is not an importer" message="The address does not name an importer." />
{:else}
	{#key instanceId}
		<DiscoveryPage {instanceId} />
	{/key}
{/if}
