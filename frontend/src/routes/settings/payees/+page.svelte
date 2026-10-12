<script lang="ts">
	import PayeeManager from '#lib/components/settings/payee-manager.svelte';
	import { PayeesStore } from '#lib/payees/store.svelte.js';

	const store = new PayeesStore();
</script>

<svelte:head>
	<title>Payees · Settings · Ledgehog</title>
</svelte:head>

<PayeeManager {store} />
