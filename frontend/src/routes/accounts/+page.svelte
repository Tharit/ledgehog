<script lang="ts">
	import { goto } from '$app/navigation';
	import { onDestroy, onMount } from 'svelte';
	import { accounts as accountDialog } from '#lib/accounts/controller.svelte.js';
	import AccountList from '#lib/components/accounts/account-list.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import { describeLoadError } from '#lib/ledger/errors.js';
	import { AccountsListStore } from '#lib/stores/accounts-list.svelte.js';

	const list = new AccountsListStore();

	onMount(() => void list.load());
	onDestroy(() => list.dispose());

	// the existing "Add account" dialog; once added, the account's page opens
	function add() {
		accountDialog.openAdd({ onadded: (account) => void goto(`/accounts/${account.id}`) });
	}

	const failure = $derived(list.error ? describeLoadError(list.error.code) : null);
</script>

<svelte:head>
	<title>Accounts · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<PageHeader
		level={1}
		title="Accounts"
		description="Every account with its balance. Open one to see what its sources said."
		actionLabel="Add account"
		onaction={add}
	/>

	{#if list.status === 'error' && failure}
		<ErrorState
			title="The accounts could not be loaded"
			message={failure.message}
			onretry={failure.retryable ? () => list.load() : undefined}
			class="max-w-none items-center p-8 text-center"
		/>
	{:else if list.status === 'loading'}
		<p class="text-sm text-muted-foreground">Loading the accounts…</p>
	{:else}
		<AccountList accounts={list.accounts} locale={list.locale} today={list.today} onadd={add} />
	{/if}
</div>
