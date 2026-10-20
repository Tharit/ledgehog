<script lang="ts">
	import { page } from '$app/state';
	import SectionTabs from '#lib/components/common/section-tabs.svelte';
	import { REPORT_TABS, sharedQuery } from '#lib/reports/params.js';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

<svelte:head>
	<title>Reports · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<h1 class="text-[28px] font-semibold">Reports</h1>
	<!-- the period and the filters follow the user from one report to the next -->
	<SectionTabs
		tabs={REPORT_TABS}
		label="Reports"
		currentPath={page.url.pathname}
		query={sharedQuery(page.url.search)}
	/>
	{@render children()}
</div>
