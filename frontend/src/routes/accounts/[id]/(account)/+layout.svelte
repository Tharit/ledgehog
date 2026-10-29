<script lang="ts">
	import { afterNavigate, goto, pushState, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, onMount, untrack } from 'svelte';
	import { accountIdOf } from '#lib/accounts/address.js';
	import { RowAddress } from '#lib/accounts/row-address.svelte.js';
	import { AccountDialogs } from '#lib/accounts/page-dialogs.svelte.js';
	import { AccountPageContext, provideAccountPage } from '#lib/accounts/page-context.svelte.js';
	import { RowDetail } from '#lib/accounts/row-detail.svelte.js';
	import { ACCOUNT_KINDS } from '#lib/accounts/kinds.js';
	import AccountActions from '#lib/components/accounts/account-actions.svelte';
	import AccountPageDialogs from '#lib/components/accounts/account-page-dialogs.svelte';
	import AccountSummary from '#lib/components/accounts/account-summary.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import NewDataNotice from '#lib/components/common/new-data-notice.svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import SectionTabs, { type SectionTab } from '#lib/components/common/section-tabs.svelte';
	import { entryForm } from '#lib/entry-form/controller.svelte.js';
	import { formatDate } from '#lib/format/index.js';
	import { AccountPageStore } from '#lib/stores/account-page.svelte.js';
	import { AccountRunsStore } from '#lib/stores/account-runs.svelte.js';
	import { refetchOnChange } from '#lib/stores/new-data.svelte.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import { session } from '#lib/stores/session.svelte.js';
	import { entryDeps } from '#lib/stores/sync.svelte.js';
	import { isBusyRefusal, refusalText, startOrReview } from '#lib/sync/entry.js';
	import type { Snippet } from 'svelte';

	// The account page (ux/views/account.md): the header, its cards and the new-data notice, then
	// the two tabs, Transactions and Runs, each its own address. The layout owns the page's state and
	// its dialogs, so a tab change reads nothing again; the upload page (`../upload`) is outside it.
	let { children }: { children: Snippet } = $props();

	const view = new AccountPageStore();
	const runs = new AccountRunsStore();
	const detail = new RowDetail();
	const dialogs = new AccountDialogs();
	view.onRefresh(() => runs.reload());
	// the runs are not a snapshot: a sync's runs appear as the ledger moves
	refetchOnChange('ledger', () => void runs.reload());

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
	// the detail follows the address at once on our own changes (the effect above covers Back,
	// Forward and links), so the dialog and the address can never disagree for a moment
	function openDetail(id: number) {
		address.open(id);
		void detail.show(id);
	}
	function closeDetail() {
		address.close();
		void detail.show(null);
	}
	function leaveDetail() {
		address.leave();
		void detail.show(null);
	}

	// the entry form writes rows of this account: the statement follows
	$effect(() =>
		entryForm.listen({
			changed: () => view.afterWrite(),
			notify: (text, error) => view.notify(text, error)
		})
	);

	// "Fetch" and "Run again" are one-item syncs of this account (ux/views/sync.md "Starting"): at
	// once, or after the sync page asked for the start of an account without coverage. A refused
	// start is a notice here, not on the sync page.
	async function fetchHere(instanceId: number) {
		if (accountId === null) return;
		const refusal = await startOrReview({ instanceId, accountId }, entryDeps(goto));
		if (!refusal) return;
		view.notify(
			refusalText(refusal),
			!isBusyRefusal(refusal),
			isBusyRefusal(refusal) ? { label: 'Open Sync', run: () => void goto('/sync') } : undefined
		);
	}

	const context = new AccountPageContext(
		view,
		runs,
		dialogs,
		openDetail,
		fetchHere,
		() => accountId
	);
	provideAccountPage(context);

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
	// the Transactions tab is the account's own address, so it is current there alone
	const tabs = $derived<readonly SectionTab[]>([
		{ href: `/accounts/${accountId}`, label: 'Transactions', exact: true },
		{ href: `/accounts/${accountId}/runs`, label: 'Runs' }
	]);
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
		>
			{#snippet icon()}
				<DimensionIcon {...resolveAccount(account)} size="comfortable" />
			{/snippet}
			{#snippet actions()}
				<AccountActions
					{account}
					onsetbalance={() => dialogs.open('balance')}
					onedit={() => dialogs.open('edit')}
					onclose={() => dialogs.open('close')}
					onreopen={() => view.reopen()}
					ondelete={() => dialogs.open('delete')}
				/>
			{/snippet}
		</PageHeader>

		<AccountSummary
			{account}
			sources={runs.sources}
			sourcesStatus={runs.sourcesStatus}
			locale={view.locale}
			today={view.today}
			onfetch={fetchHere}
		/>

		<!-- one reserved line, so a notice appearing never moves the rows (patterns §7) -->
		<NewDataNotice stale={view.news.stale} onrefresh={() => view.afterWrite()} notice={view.notice}>
			{#snippet noticeAction()}
				{#if view.notice?.action}
					{@const run = view.notice.action}
					<ActionButton variant="link" class="h-auto p-0" onclick={run.run}
						>{run.label}</ActionButton
					>
				{/if}
			{/snippet}
		</NewDataNotice>

		<!-- a clearance account has no runs, so no tabs: its statement follows the header -->
		{#if account.kind !== 'clearance'}
			<SectionTabs {tabs} label="Account sections" currentPath={page.url.pathname} />
		{/if}

		{@render children()}
	{/if}
</div>

{#if account}
	<AccountPageDialogs
		onclosefocus={(event) => {
			// a click on a row focused the list; giving focus back must not scroll it into view
			event.preventDefault();
			context.focusStatement?.();
		}}
		{view}
		{runs}
		{detail}
		detailOpen={address.id !== null}
		{dialogs}
		timeZone={session.config?.timezone ?? 'UTC'}
		onclosedetail={closeDetail}
		onleavedetail={leaveDetail}
		onopendetail={openDetail}
		ondeleted={() => void goto('/accounts')}
	/>
{/if}
