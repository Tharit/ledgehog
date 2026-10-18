<script lang="ts">
	import AccountDialogs from '#lib/components/accounts/account-dialogs.svelte';
	import DiscoveryPage from './discovery-page.svelte';

	// Test harness: the discovery page with the root layout's account dialog beside it, as the app
	// mounts them, since "Add and link" opens the one global Add account dialog.
	let { instanceId }: { instanceId: number } = $props();
</script>

<DiscoveryPage {instanceId} />
<AccountDialogs />
