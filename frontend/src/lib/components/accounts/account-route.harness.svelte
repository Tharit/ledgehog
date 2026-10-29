<script lang="ts">
	import Layout from '../../../routes/accounts/[id]/(account)/+layout.svelte';
	import Transactions from '../../../routes/accounts/[id]/(account)/+page.svelte';
	import Runs from '../../../routes/accounts/[id]/(account)/runs/+page.svelte';

	// The account page as the router builds it: the layout around one of its two tabs.
	let { tab = 'transactions' }: { tab?: 'transactions' | 'runs' } = $props();
</script>

<Layout>
	{#if tab === 'runs'}<Runs />{:else}<Transactions />{/if}
</Layout>
