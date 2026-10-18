<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import InstanceEditorPage from '#lib/components/importers/instance-editor-page.svelte';
	import { instanceUrl, intentOf, positiveId } from '#lib/importers/links.js';

	const instanceId = $derived(positiveId(page.params.id));
	// how the page was reached, read once: the address is tidied after the editor has used it
	const intent = untrack(() => intentOf(page.url.search));
</script>

<svelte:head>
	<title>Importer · Settings · Ledgehog</title>
</svelte:head>

{#if instanceId === null}
	<ErrorState title="This is not an importer" message="The address does not name an importer." />
{:else}
	{#key instanceId}
		<InstanceEditorPage
			{instanceId}
			{intent}
			onleave={(url) => goto(url)}
			onopen={(url) => goto(url)}
			ontidy={() => goto(instanceUrl(instanceId), { replaceState: true })}
		/>
	{/key}
{/if}
