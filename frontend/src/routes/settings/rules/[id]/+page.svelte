<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import RuleEditorPage from '#lib/components/rules/rule-editor-page.svelte';

	const ruleId = $derived.by(() => {
		const id = Number(page.params.id);
		return Number.isSafeInteger(id) && id > 0 ? id : null;
	});
</script>

<svelte:head>
	<title>Rule · Settings · Ledgehog</title>
</svelte:head>

{#if ruleId === null}
	<ErrorState title="This is not a rule" message="The address does not name a rule." />
{:else}
	{#key ruleId}
		<RuleEditorPage {ruleId} onleave={(url) => goto(url)} />
	{/key}
{/if}
