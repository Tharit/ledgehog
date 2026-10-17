<script lang="ts">
	import type { AccountDialogs } from '#lib/accounts/page-dialogs.svelte.js';
	import type { RowDetail } from '#lib/accounts/row-detail.svelte.js';
	import type { MarkResult } from '#lib/accounts/duplicate-flow.svelte.js';
	import type { AccountPageStore } from '#lib/stores/account-page.svelte.js';
	import type { AccountRunsStore } from '#lib/stores/account-runs.svelte.js';
	import { unitPanel } from '#lib/units/panel-instance.js';
	import AccountEditDialog from './account-edit-dialog.svelte';
	import BalanceDialog from './balance-dialog.svelte';
	import CloseAccountDialog from './close-account-dialog.svelte';
	import DeleteAccountDialog from './delete-account-dialog.svelte';
	import MarkDuplicateDialog from './mark-duplicate-dialog.svelte';
	import RecordDeleteDialog from './record-delete-dialog.svelte';
	import RevertRunDialog from './revert-run-dialog.svelte';
	import RowDetailDialog from './row-detail-dialog.svelte';

	// Every dialog of the account page, mounted once: the row detail (addressed by `?source=`) and
	// the decision and form dialogs the page opens one at a time. Each write ends in the page store's
	// refetch (ux/views/account.md: a snapshot, refetched after its own writes).
	let {
		view,
		runs,
		detail,
		dialogs,
		timeZone = 'UTC',
		onclosedetail,
		onleavedetail,
		onclosefocus,
		onopendetail,
		ondeleted
	}: {
		view: AccountPageStore;
		runs: AccountRunsStore;
		detail: RowDetail;
		dialogs: AccountDialogs;
		timeZone?: string;
		/** the detail was closed by the user: back to where the page was */
		onclosedetail: () => void;
		/** the detail's address is left for something else (the panel, a dialog): `?source=` goes at once */
		onleavedetail: () => void;
		/** the detail closed: the page places focus itself, without scrolling */
		onclosefocus?: (event: Event) => void;
		/** another row's detail is asked for (the row a duplicate duplicates) */
		onopendetail: (sourceId: number) => void;
		/** the account was deleted: the page has nothing left to show */
		ondeleted: () => void;
	} = $props();

	let clearing = $state(false);

	const account = $derived(view.account);

	async function notDuplicate() {
		const id = detail.id;
		if (id === null || clearing) return;
		clearing = true;
		const done = await view.notDuplicate(id);
		clearing = false;
		if (done) onleavedetail();
		else await detail.reload();
	}

	function openReview(entryId: number) {
		onleavedetail();
		unitPanel.open(entryId);
	}

	async function marked(result: MarkResult) {
		dialogs.close();
		onleavedetail();
		await view.afterWrite();
		const returned = result.out.partners.length;
		view.notify(
			`Marked as a duplicate.${returned > 0 ? ` ${returned} ${returned === 1 ? 'entry' : 'entries'} returned to review.` : ''}`
		);
	}
</script>

<RowDetailDialog
	open={detail.id !== null && !dialogs.is('mark')}
	status={detail.status}
	provenance={detail.provenance}
	locale={view.locale}
	{timeZone}
	busy={clearing}
	onclose={onclosedetail}
	{onclosefocus}
	onretry={() => detail.reload()}
	onopenreview={openReview}
	onopenoriginal={onopendetail}
	onmark={() => dialogs.open('mark')}
	onnotduplicate={notDuplicate}
	onedit={() => {
		const row = detail.provenance;
		onleavedetail();
		if (row) void view.openAuthored(row, 'edit');
	}}
	ondelete={() => {
		const row = detail.provenance;
		onleavedetail();
		if (row) void view.openAuthored(row, 'delete');
	}}
/>

<MarkDuplicateDialog
	open={dialogs.is('mark')}
	row={detail.provenance}
	locale={view.locale}
	onclose={() => dialogs.close()}
	onmarked={marked}
/>

{#if account}
	<BalanceDialog
		open={dialogs.is('balance')}
		{account}
		record={dialogs.record}
		today={view.today}
		locale={view.locale}
		onclose={() => dialogs.close()}
		onsaved={async (out) => {
			dialogs.close();
			await view.recordWritten(out);
		}}
	/>
	<RecordDeleteDialog
		open={dialogs.is('record-delete')}
		record={dialogs.record}
		locale={view.locale}
		onclose={() => dialogs.close()}
		ondeleted={async (out) => {
			dialogs.close();
			view.applyAccount(out.account);
			await view.afterWrite();
			view.notify(
				out.settle.error
					? 'Balance record deleted. Derived figures may be stale until the next action.'
					: 'Balance record deleted.'
			);
		}}
	/>
	<AccountEditDialog
		open={dialogs.is('edit')}
		{account}
		onclose={() => dialogs.close()}
		onsaved={(out) => {
			dialogs.close();
			view.applyAccount(out.account);
		}}
	/>
	<CloseAccountDialog
		open={dialogs.is('close')}
		{account}
		today={view.today}
		locale={view.locale}
		onclose={() => dialogs.close()}
		onclosed={async (out) => {
			dialogs.close();
			view.applyAccount(out.account);
			await view.afterWrite();
			view.notify('Account closed.');
		}}
	/>
	<DeleteAccountDialog
		open={dialogs.is('delete')}
		{account}
		onclose={() => dialogs.close()}
		ondeleted={() => {
			dialogs.close();
			ondeleted();
		}}
		onclosewith={() => dialogs.open('close')}
	/>
	{@const run = runs.runs.find((r) => r.id === dialogs.runId) ?? null}
	<RevertRunDialog
		open={dialogs.is('revert')}
		{run}
		label={run ? runs.instanceLabel(run) : ''}
		locale={view.locale}
		{timeZone}
		onclose={() => dialogs.close()}
		onreverted={async () => {
			dialogs.close();
			await view.afterWrite();
			view.notify('Run reverted.');
		}}
	/>
{/if}
