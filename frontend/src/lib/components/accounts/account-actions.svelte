<script lang="ts">
	import EllipsisIcon from '@lucide/svelte/icons/ellipsis';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import IconButton from '#lib/components/common/icon-button.svelte';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.js';
	import type { Account } from '#lib/types/domain.js';

	// The account's secondary actions (ux/views/account.md "Header"), drawn in the page header
	// before "Add entry": "Set balance", "View entries" and the `⋯` menu with Edit, Close… or
	// Reopen, and Delete… last and destructive.
	let {
		account,
		onsetbalance,
		onedit,
		onclose,
		onreopen,
		ondelete
	}: {
		account: Account;
		onsetbalance: () => void;
		onedit: () => void;
		onclose: () => void;
		onreopen: () => void;
		ondelete: () => void;
	} = $props();

	const closed = $derived(account.closed_on !== null);
</script>

<ActionButton variant="outline" onclick={onsetbalance}>Set balance</ActionButton>
<ActionButton variant="outline" href={`/ledger?account_id=${account.id}`}>View entries</ActionButton
>
<DropdownMenu.Root>
	<DropdownMenu.Trigger>
		{#snippet child({ props })}
			<IconButton
				tooltip={false}
				verb="More actions"
				name={account.name}
				label={`More actions for ${account.name}`}
				{...props}
			>
				<EllipsisIcon aria-hidden="true" />
			</IconButton>
		{/snippet}
	</DropdownMenu.Trigger>
	<DropdownMenu.Content align="end" class="min-w-44">
		<DropdownMenu.Item onSelect={onedit}>Edit</DropdownMenu.Item>
		{#if closed}
			<DropdownMenu.Item onSelect={onreopen}>Reopen</DropdownMenu.Item>
		{:else}
			<DropdownMenu.Item onSelect={onclose}>Close…</DropdownMenu.Item>
		{/if}
		<DropdownMenu.Separator />
		<DropdownMenu.Item variant="destructive" onSelect={ondelete}>Delete…</DropdownMenu.Item>
	</DropdownMenu.Content>
</DropdownMenu.Root>
