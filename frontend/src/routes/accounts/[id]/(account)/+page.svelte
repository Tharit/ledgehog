<script lang="ts">
	import { onDestroy } from 'svelte';
	import { useAccountPage } from '#lib/accounts/page-context.svelte.js';
	import StatementTable from '#lib/components/accounts/statement-table.svelte';

	// The Transactions tab (ux/views/account.md "The statement"); the layout owns the page's state.
	const ctx = useAccountPage();
	const { view, dialogs } = ctx;
	const account = $derived(view.account);

	let table = $state<ReturnType<typeof StatementTable> | null>(null);
	$effect(() => {
		ctx.focusStatement = table ? () => table?.focusList() : null;
	});
	onDestroy(() => (ctx.focusStatement = null));
</script>

{#if account}
	<StatementTable
		bind:this={table}
		items={view.statement.items}
		total={view.statement.total}
		status={view.statement.status}
		{account}
		loadingMore={view.statement.loadingMore}
		error={view.statement.error}
		moreError={view.statement.moreError}
		locale={view.locale}
		onopen={ctx.openDetail}
		onedit={(record) => dialogs.open('balance', { record })}
		ondelete={(record) => dialogs.open('record-delete', { record })}
		onloadmore={() => view.statement.loadMore()}
		onretry={() => {
			const id = ctx.accountId();
			if (id !== null) void view.statement.load(id);
		}}
	/>
{/if}
