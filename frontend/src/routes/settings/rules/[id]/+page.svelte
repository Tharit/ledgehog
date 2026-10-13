<script lang="ts">
	import { goto, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import RuleEditorPage from '#lib/components/rules/rule-editor-page.svelte';
	import { parseExampleId, withExample } from '#lib/rules/example.js';

	const ruleId = $derived.by(() => {
		const id = Number(page.params.id);
		return Number.isSafeInteger(id) && id > 0 ? id : null;
	});
	// the example the page came with; later changes only rewrite the address (see the new-rule page)
	const exampleId = untrack(() => parseExampleId(page.url.search));
</script>

<svelte:head>
	<title>Rule · Settings · Ledgehog</title>
</svelte:head>

{#if ruleId === null}
	<ErrorState title="This is not a rule" message="The address does not name a rule." />
{:else}
	{#key ruleId}
		<RuleEditorPage
			{ruleId}
			{exampleId}
			onleave={(url) => goto(url)}
			onexample={(id) => replaceState(withExample(page.url, id), page.state)}
		/>
	{/key}
{/if}
