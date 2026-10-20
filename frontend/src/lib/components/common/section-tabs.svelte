<script lang="ts" module>
	export type SectionTab = { href: string; label: string };
</script>

<script lang="ts">
	// The tab bar of an area (Settings, Reports): links, so each screen has its own address. The
	// current tab is the one whose path the current path is, or is below. `query` is carried onto
	// every link (the reports' shared controls stay when the tab changes).
	let {
		tabs,
		label,
		currentPath,
		query = ''
	}: {
		tabs: readonly SectionTab[];
		/** the navigation's accessible name */
		label: string;
		currentPath: string;
		query?: string;
	} = $props();

	const suffix = $derived(query === '' ? '' : `?${query.replace(/^\?/, '')}`);
</script>

<nav aria-label={label} class="flex gap-1 border-b border-border">
	{#each tabs as tab (tab.href)}
		{@const active = currentPath === tab.href || currentPath.startsWith(tab.href + '/')}
		<a
			href={`${tab.href}${suffix}`}
			aria-current={active ? 'page' : undefined}
			class="-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground hover:text-foreground aria-[current=page]:border-primary aria-[current=page]:font-medium aria-[current=page]:text-foreground"
		>
			{tab.label}
		</a>
	{/each}
</nav>
