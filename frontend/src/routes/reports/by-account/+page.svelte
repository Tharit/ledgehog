<script lang="ts">
	import { getByAccount } from '#lib/api/index.js';
	import ByAccountView from '#lib/components/reports/by-account-view.svelte';
	import ReportControls from '#lib/components/reports/report-controls.svelte';
	import ReportFrame from '#lib/components/reports/report-frame.svelte';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';
	import { useReport } from '#lib/stores/report-route.svelte.js';

	// *By account* (reports.md): one range and the tag filter; its accounts are what it shows, so an
	// account in the address is ignored here. A computed view, read again when the controls or the
	// ledger change.
	const TOP = 10;
	const report = useReport('by-account', (p, signal) =>
		getByAccount({ from: p.from, to: p.to, tagIds: p.tagIds, top: TOP, signal })
	);
	const { view } = report;
</script>

<svelte:head>
	<title>By account · Reports · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<ReportControls
		report="by-account"
		params={report.params}
		lookups={lookupsStore.lookups}
		today={report.today}
		locale={report.locale}
		accounts={false}
		onchange={report.change}
	/>
	<ReportFrame
		data={view.data}
		status={view.status}
		error={view.error}
		onretry={() => view.retry()}
	>
		{#snippet children(data)}
			<ByAccountView
				report={data}
				categories={lookupsStore.lookups.categories}
				accounts={lookupsStore.lookups.accounts}
				scope={{ from: data.from, to: data.to, accountIds: [], tagIds: report.params.tagIds }}
				locale={report.locale}
			/>
		{/snippet}
	</ReportFrame>
</div>
