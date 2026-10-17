<script lang="ts">
	import { onMount } from 'svelte';
	import { RowAddress } from '#lib/accounts/row-address.svelte.js';
	import { RowDetail } from '#lib/accounts/row-detail.svelte.js';
	import type { StatementItem } from '#lib/types/domain.js';
	import RowDetailDialog from './row-detail-dialog.svelte';
	import StatementTable from './statement-table.svelte';

	// Test harness: the statement and the row detail wired the way the account page wires them
	// (the address as state, the detail following it), without the router.
	let { items }: { items: StatementItem[] } = $props();

	const address = new RowAddress();
	const detail = new RowDetail();
	onMount(() => {
		address.sync();
		const follow = () => address.sync();
		window.addEventListener('popstate', follow);
		return () => window.removeEventListener('popstate', follow);
	});
	$effect(() => {
		void detail.show(address.id);
	});
</script>

<StatementTable
	{items}
	total={items.length}
	status="ready"
	account={{ kind: 'checking', records_since_zero: null }}
	onopen={(id) => address.open(id)}
/>
<RowDetailDialog
	open={detail.id !== null}
	status={detail.status}
	provenance={detail.provenance}
	onclose={() => address.close()}
/>
