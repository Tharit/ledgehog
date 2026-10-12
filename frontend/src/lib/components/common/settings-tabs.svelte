<script lang="ts" module>
	export type SettingsTab = { href: string; label: string };

	/** The areas of Settings: the management screens of architecture §6.2. */
	export const SETTINGS_TABS: readonly SettingsTab[] = [
		{ href: '/settings/categories', label: 'Categories' },
		{ href: '/settings/payees', label: 'Payees' },
		{ href: '/settings/rules', label: 'Rules' }
	];
</script>

<script lang="ts">
	// The tab bar of the Settings area: links, so each screen has its own address.
	let {
		tabs = SETTINGS_TABS,
		currentPath
	}: { tabs?: readonly SettingsTab[]; currentPath: string } = $props();
</script>

<nav aria-label="Settings sections" class="flex gap-1 border-b border-border">
	{#each tabs as tab (tab.href)}
		{@const active = currentPath === tab.href || currentPath.startsWith(tab.href + '/')}
		<a
			href={tab.href}
			aria-current={active ? 'page' : undefined}
			class="-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground hover:text-foreground aria-[current=page]:border-primary aria-[current=page]:font-medium aria-[current=page]:text-foreground"
		>
			{tab.label}
		</a>
	{/each}
</nav>
