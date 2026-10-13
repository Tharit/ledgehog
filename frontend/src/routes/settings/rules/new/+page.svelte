<script lang="ts">
	import { goto, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import RuleEditorPage from '#lib/components/rules/rule-editor-page.svelte';
	import { parseExampleId, withExample } from '#lib/rules/example.js';

	// `?from=<entry id>` opens the editor with that entry as the example. The editor is made once,
	// with the example the page came with: choosing or clearing one later only rewrites the address
	// (replaced, so Back is not polluted) and never remakes the editor and its draft.
	const exampleId = untrack(() => parseExampleId(page.url.search));
</script>

<svelte:head>
	<title>Add rule · Settings · Ledgehog</title>
</svelte:head>

<RuleEditorPage
	{exampleId}
	onleave={(url) => goto(url)}
	onexample={(id) => replaceState(withExample(page.url, id), page.state)}
/>
