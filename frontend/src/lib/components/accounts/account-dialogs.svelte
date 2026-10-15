<script lang="ts">
	import { accounts } from '#lib/accounts/controller.svelte.js';
	import AddAccountDialog from './add-account-dialog.svelte';

	// The account dialogs, mounted once in the root layout and opened by the account controller.
</script>

<AddAccountDialog open={accounts.adding} onclose={() => accounts.close()} />
