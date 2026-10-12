<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import RuleEditorPage from '#lib/components/rules/rule-editor-page.svelte';
	import { parseFromParams } from '#lib/rules/prefill.js';

	const from = $derived(parseFromParams(page.url.search));
</script>

<svelte:head>
	<title>New rule · Settings · Ledgehog</title>
</svelte:head>

{#key from?.id}
	<RuleEditorPage {from} onleave={(url) => goto(url)} />
{/key}
