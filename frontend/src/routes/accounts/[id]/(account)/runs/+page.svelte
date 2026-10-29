<script lang="ts">
	import { goto } from '$app/navigation';
	import { useAccountPage } from '#lib/accounts/page-context.svelte.js';
	import AccountRuns from '#lib/components/accounts/account-runs.svelte';
	import { session } from '#lib/stores/session.svelte.js';

	// The Runs tab (ux/views/account.md "The Runs tab"): the whole import log. A clearance account has
	// no runs and no tabs: its address here goes to its statement.
	const ctx = useAccountPage();
	const { view, runs, dialogs } = ctx;
	const account = $derived(view.account);

	$effect(() => {
		if (account?.kind === 'clearance') void goto(`/accounts/${account.id}`, { replaceState: true });
	});
</script>

{#if account && account.kind !== 'clearance'}
	<AccountRuns
		runs={runs.runs}
		status={runs.runsStatus}
		instanceLabel={runs.instanceLabel}
		importerKind={runs.importerKind}
		currency={account.currency}
		locale={view.locale}
		timeZone={session.config?.timezone ?? 'UTC'}
		onrevert={(run) => dialogs.open('revert', { runId: run.id })}
		onretry={() => {
			const id = ctx.accountId();
			if (id !== null) void runs.load(id);
		}}
		onrunagain={(run) => run.instance_id !== null && ctx.fetchHere(run.instance_id)}
	/>
{/if}
