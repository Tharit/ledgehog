<script lang="ts">
	import { getBalances } from '#lib/api/index.js';
	import BalancesView from '#lib/components/reports/balances-view.svelte';
	import ReportControls from '#lib/components/reports/report-controls.svelte';
	import ReportFrame from '#lib/components/reports/report-frame.svelte';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';
	import { useReport } from '#lib/stores/report-route.svelte.js';

	// *Balances* (reports.md): the month-end balances of the range, net worth and accounts. Of every
	// account, so it has no account or tag filter.
	const report = useReport('balances', (p, signal) => getBalances(p.from, p.to, signal));
	const { view } = report;
</script>

<svelte:head>
	<title>Balances · Reports · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<ReportControls
		report="balances"
		params={report.params}
		lookups={lookupsStore.lookups}
		today={report.today}
		locale={report.locale}
		filters={false}
		onchange={report.change}
	/>
	<ReportFrame
		data={view.data}
		status={view.status}
		error={view.error}
		onretry={() => view.retry()}
	>
		{#snippet children(data)}
			<BalancesView report={data} accounts={lookupsStore.lookups.accounts} locale={report.locale} />
		{/snippet}
	</ReportFrame>
</div>
