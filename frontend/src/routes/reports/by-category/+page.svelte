<script lang="ts">
	import { getByCategory } from '#lib/api/index.js';
	import ByCategoryView from '#lib/components/reports/by-category-view.svelte';
	import ReportControls from '#lib/components/reports/report-controls.svelte';
	import ReportFrame from '#lib/components/reports/report-frame.svelte';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';
	import { useReport } from '#lib/stores/report-route.svelte.js';

	// *By category* (reports.md): one range; a computed view that keeps its figures on screen and
	// reads again when the controls or the ledger change.
	const TOP = 6;
	const report = useReport('by-category', (p, signal) =>
		getByCategory({
			from: p.from,
			to: p.to,
			kind: p.kind,
			accountIds: p.accountIds,
			tagIds: p.tagIds,
			top: TOP,
			signal
		})
	);
	const { view } = report;
</script>

<svelte:head>
	<title>By category · Reports · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<ReportControls
		report="by-category"
		params={report.params}
		lookups={lookupsStore.lookups}
		today={report.today}
		locale={report.locale}
		kind
		onchange={report.change}
	/>
	<ReportFrame
		data={view.data}
		status={view.status}
		error={view.error}
		onretry={() => view.retry()}
	>
		{#snippet children(data)}
			<ByCategoryView
				report={data}
				categories={lookupsStore.lookups.categories}
				scope={{
					from: data.from,
					to: data.to,
					accountIds: report.params.accountIds,
					tagIds: report.params.tagIds
				}}
				locale={report.locale}
			/>
		{/snippet}
	</ReportFrame>
</div>
