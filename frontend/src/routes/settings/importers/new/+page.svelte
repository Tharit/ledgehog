<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import InstanceEditorPage from '#lib/components/importers/instance-editor-page.svelte';
	import { importerOf } from '#lib/importers/links.js';

	// `?importer=<catalog name>` names what is added. The editor is made once, for that importer.
	const importer = untrack(() => importerOf(page.url.search));
</script>

<svelte:head>
	<title>Add importer · Settings · Ledgehog</title>
</svelte:head>

{#if importer === null}
	<ErrorState
		title="No importer chosen"
		message="Choose what to add from “Add importer” on the importers list."
	/>
{:else}
	<InstanceEditorPage {importer} onleave={(url) => goto(url)} />
{/if}
