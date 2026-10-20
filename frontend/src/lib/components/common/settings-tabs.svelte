<script lang="ts" module>
	import type { SectionTab } from './section-tabs.svelte';

	export type SettingsTab = SectionTab;

	/** The areas of Settings: the management screens of architecture §6.2. */
	export const SETTINGS_TABS: readonly SettingsTab[] = [
		{ href: '/settings/categories', label: 'Categories' },
		{ href: '/settings/payees', label: 'Payees' },
		{ href: '/settings/tags', label: 'Tags' },
		{ href: '/settings/rules', label: 'Rules' },
		{ href: '/settings/importers', label: 'Importers' }
	];
</script>

<script lang="ts">
	import SectionTabs from './section-tabs.svelte';

	// The tab bar of the Settings area.
	let {
		tabs = SETTINGS_TABS,
		currentPath
	}: { tabs?: readonly SettingsTab[]; currentPath: string } = $props();
</script>

<SectionTabs {tabs} label="Settings sections" {currentPath} />
