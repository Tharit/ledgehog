<script lang="ts">
	import type { AccountDialogs } from '#lib/accounts/page-dialogs.svelte.js';
	import type { RowAddress } from '#lib/accounts/row-address.svelte.js';
	import type { RowDetail } from '#lib/accounts/row-detail.svelte.js';
	import type { AccountPageStore } from '#lib/stores/account-page.svelte.js';
	import type { AccountRunsStore } from '#lib/stores/account-runs.svelte.js';
	import AccountPageDialogs from './account-page-dialogs.svelte';

	// Test harness: the account page's dialogs wired to the address the way the route wires them.
	let {
		view,
		runs,
		detail,
		dialogs,
		address
	}: {
		view: AccountPageStore;
		runs: AccountRunsStore;
		detail: RowDetail;
		dialogs: AccountDialogs;
		address: RowAddress;
	} = $props();

	function closeDetail() {
		address.close();
		void detail.show(null);
	}
	function leaveDetail() {
		address.leave();
		void detail.show(null);
	}
	function openDetail(id: number) {
		address.open(id);
		void detail.show(id);
	}
</script>

<AccountPageDialogs
	{view}
	{runs}
	{detail}
	detailOpen={address.id !== null}
	{dialogs}
	onclosedetail={closeDetail}
	onleavedetail={leaveDetail}
	onopendetail={openDetail}
	ondeleted={() => {}}
/>
