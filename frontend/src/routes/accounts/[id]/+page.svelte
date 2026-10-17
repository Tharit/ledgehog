<script lang="ts">
	import { afterNavigate, goto, pushState, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, onMount, untrack } from 'svelte';
	import { accountIdOf } from '#lib/accounts/address.js';
	import { RowAddress } from '#lib/accounts/row-address.svelte.js';
	import { AccountDialogs } from '#lib/accounts/page-dialogs.svelte.js';
	import { RowDetail } from '#lib/accounts/row-detail.svelte.js';
	import { ACCOUNT_KINDS } from '#lib/accounts/kinds.js';
	import AccountPageDialogs from '#lib/components/accounts/account-page-dialogs.svelte';
	import AccountRuns from '#lib/components/accounts/account-runs.svelte';
	import AccountSummary from '#lib/components/accounts/account-summary.svelte';
	import StatementTable from '#lib/components/accounts/statement-table.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import NoticeLine from '#lib/components/common/notice-line.svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import { entryForm } from '#lib/entry-form/controller.svelte.js';
	import { formatDate } from '#lib/format/index.js';
	import { AccountPageStore } from '#lib/stores/account-page.svelte.js';
	import { AccountRunsStore } from '#lib/stores/account-runs.svelte.js';
	import { session } from '#lib/stores/session.svelte.js';

	const view = new AccountPageStore();
	const runs = new AccountRunsStore();
	const detail = new RowDetail();
	const dialogs = new AccountDialogs();
	view.onRefresh(() => runs.reload());

	const accountId = $derived(accountIdOf(page.params.id));

	// the account in the address: its facts, its runs and sources and the first page of its
	// statement (a new id, a new account)
	$effect(() => {
		const id = accountId;
		if (id === null) return;
		untrack(() => {
			void view.open(id);
			void runs.load(id);
		});
	});

	// `?source=` is the row detail: it opens for whatever id the address names, whatever page of the
	// statement the row is on, and so does a link from a run summary. Shallow routing does not move
	// `page.url`, so the real address is read (as the unit panel does) after our own changes, after
	// Back and Forward, and after a navigation.
	const address = new RowAddress({
		url: () => new URL(location.href),
		push: (url) => pushState(url, {}),
		replace: (url) => replaceState(url, {}),
		back: (steps) => history.go(-steps)
	});
	onMount(() => {
		address.sync();
		const follow = () => address.sync();
		window.addEventListener('popstate', follow);
		return () => window.removeEventListener('popstate', follow);
	});
	afterNavigate(() => address.sync());
	$effect(() => {
		const id = address.id;
		untrack(() => void detail.show(id));
	});
	const openDetail = (id: number) => address.open(id);
	const closeDetail = () => address.close();
	const leaveDetail = () => address.leave();

	// the entry form writes rows of this account: the statement follows
	$effect(() =>
		entryForm.listen({
			changed: () => view.afterWrite(),
			notify: (text, error) => view.notify(text, error)
		})
	);

	onDestroy(() => {
		view.dispose();
		runs.dispose();
		detail.dispose();
	});

	const account = $derived(view.account);
	const kindLabel = $derived(
		ACCOUNT_KINDS.find((k) => k.kind === account?.kind)?.label ?? account?.kind
	);
	const description = $derived(
		account
			? [
					kindLabel,
					account.currency,
					account.closed_on ? `closed on ${formatDate(account.closed_on, view.locale)}` : null
				]
					.filter(Boolean)
					.join(' · ')
			: undefined
	);
</script>

<svelte:head>
	<title>{account ? `${account.name} · Accounts` : 'Account'} · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	{#if view.status === 'missing' || accountId === null}
		<PageHeader level={1} title="Account not found" />
		<Notice>
			This account does not exist (any more).
			{#snippet action()}
				<ActionButton variant="link" class="h-auto p-0" href="/accounts">All accounts</ActionButton>
			{/snippet}
		</Notice>
	{:else if view.status === 'error'}
		<PageHeader level={1} title="Account" />
		<ErrorState
			title="The account could not be loaded"
			message="The server could not answer this request. Try again in a moment."
			onretry={() => accountId !== null && view.open(accountId)}
			class="max-w-none items-center p-8 text-center"
		/>
	{:else if !account}
		<PageHeader level={1} title="Account" />
		<p class="text-sm text-muted-foreground">Loading the account…</p>
	{:else}
		<PageHeader
			level={1}
			title={account.name}
			{description}
			actionLabel={account.synced ? undefined : 'Add entry'}
			onaction={() => entryForm.openAdd({ filtered: [account.id] })}
		/>

		<AccountSummary
			{account}
			sources={runs.sources}
			sourcesStatus={runs.sourcesStatus}
			locale={view.locale}
			today={view.today}
			onsetbalance={() => dialogs.open('balance')}
			onedit={() => dialogs.open('edit')}
			onclose={() => dialogs.open('close')}
			onreopen={() => view.reopen()}
			ondelete={() => dialogs.open('delete')}
		/>

		<!-- one reserved line, so a notice appearing never moves the rows (patterns §7) -->
		<NoticeLine notice={view.notice}>
			{#snippet action()}
				{#if view.notice?.action}
					{@const run = view.notice.action}
					<ActionButton variant="link" class="h-auto p-0" onclick={run.run}
						>{run.label}</ActionButton
					>
				{/if}
			{/snippet}
		</NoticeLine>

		<AccountRuns
			runs={runs.runs}
			status={runs.runsStatus}
			instanceLabel={runs.instanceLabel}
			showAll={runs.showAll}
			currency={account.currency}
			locale={view.locale}
			timeZone={session.config?.timezone ?? 'UTC'}
			onshowall={() => (runs.showAll = true)}
			onrevert={(run) => dialogs.open('revert', { runId: run.id })}
			onretry={() => accountId !== null && runs.load(accountId)}
		/>

		<StatementTable
			items={view.statement.items}
			total={view.statement.total}
			status={view.statement.status}
			{account}
			loadingMore={view.statement.loadingMore}
			error={view.statement.error}
			moreError={view.statement.moreError}
			locale={view.locale}
			onopen={openDetail}
			onedit={(record) => dialogs.open('balance', { record })}
			ondelete={(record) => dialogs.open('record-delete', { record })}
			onloadmore={() => view.statement.loadMore()}
			onretry={() => accountId !== null && view.statement.load(accountId)}
		/>
	{/if}
</div>

{#if account}
	<AccountPageDialogs
		{view}
		{runs}
		{detail}
		{dialogs}
		timeZone={session.config?.timezone ?? 'UTC'}
		onclosedetail={closeDetail}
		onleavedetail={leaveDetail}
		onopendetail={openDetail}
		ondeleted={() => void goto('/accounts')}
	/>
{/if}
