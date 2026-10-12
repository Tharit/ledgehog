<script lang="ts">
	import { page } from '$app/state';
	import SettingsTabs from '#lib/components/common/settings-tabs.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

<svelte:head>
	<title>Settings · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<h1 class="text-[28px] font-semibold">Settings</h1>
	<SettingsTabs currentPath={page.url.pathname} />
	{@render children()}
</div>
