<script lang="ts">
	import { getOverTime } from '#lib/api/index.js';
	import OverTimeView from '#lib/components/reports/over-time-view.svelte';
	import ReportControls from '#lib/components/reports/report-controls.svelte';
	import ReportFrame from '#lib/components/reports/report-frame.svelte';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';
	import { useReport } from '#lib/stores/report-route.svelte.js';

	// *Over time* (reports.md): the range cut into months, quarters or years. The default mode is
	// *Income and expense*; *By category* adds the kind.
	const report = useReport('over-time', (p, signal) =>
		getOverTime({
			from: p.from,
			to: p.to,
			step: p.step,
			mode: p.mode === 'category' ? 'category' : 'savings',
			kind: p.kind,
			accountIds: p.accountIds,
			tagIds: p.tagIds,
			signal
		})
	);
	const { view } = report;
</script>

<svelte:head>
	<title>Over time · Reports · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<ReportControls
		report="over-time"
		params={report.params}
		lookups={lookupsStore.lookups}
		today={report.today}
		locale={report.locale}
		mode
		kind={report.params.mode === 'category'}
		step
		onchange={report.change}
	/>
	<ReportFrame
		data={view.data}
		status={view.status}
		error={view.error}
		onretry={() => view.retry()}
	>
		{#snippet children(data)}
			<OverTimeView
				report={data}
				categories={lookupsStore.lookups.categories}
				scope={{
					from: report.params.from,
					to: report.params.to,
					accountIds: report.params.accountIds,
					tagIds: report.params.tagIds
				}}
				locale={report.locale}
			/>
		{/snippet}
	</ReportFrame>
</div>
