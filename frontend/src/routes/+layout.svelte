<script lang="ts">
	import './layout.css';
	import { afterNavigate, goto, pushState, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import ListIcon from '@lucide/svelte/icons/list';
	import ListChecksIcon from '@lucide/svelte/icons/list-checks';
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import favicon from '#lib/assets/favicon.svg';
	import AppShell, { type NavItem } from '#lib/components/common/app-shell.svelte';
	import AccountDialogs from '#lib/components/accounts/account-dialogs.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import EntryFormDialogs from '#lib/components/entry-form/entry-form-dialogs.svelte';
	import PanelNavigationGuard from '#lib/components/units/panel-navigation-guard.svelte';
	import UnitPanelView from '#lib/components/units/unit-panel.svelte';
	import { entryForm } from '#lib/entry-form/controller.svelte.js';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';
	import { session } from '#lib/stores/session.svelte.js';
	import { setPanelNav, unitPanel } from '#lib/units/panel-instance.js';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	// Only routes that exist (design §10).
	const nav: NavItem[] = [
		{ href: '/ledger', label: 'Ledger', icon: ListIcon },
		{ href: '/review', label: 'Review', icon: ListChecksIcon }
	];
	// at the bottom of the sidebar, as in the mockup (design §5); /settings opens its first tab
	const footerNav: NavItem[] = [
		{ href: '/settings', label: 'Settings', icon: SettingsIcon, match: '/settings' }
	];

	const onLogin = $derived(page.url.pathname === '/login');

	onMount(() => {
		void session.start();
		// the work panel follows the address (`?unit=`): the router's shallow routing keeps its
		// history entries in step with SvelteKit's, Back and Forward re-read the address
		setPanelNav({
			url: () => new URL(location.href),
			push: (url) => pushState(url, {}),
			replace: (url) => replaceState(url, {}),
			back: () => history.back()
		});
		const follow = () => {
			if (session.status === 'authenticated') unitPanel.sync();
		};
		window.addEventListener('popstate', follow);
		return () => {
			window.removeEventListener('popstate', follow);
			setPanelNav(null);
		};
	});

	afterNavigate(() => {
		if (session.status === 'authenticated') unitPanel.sync();
	});

	// a reload or a shared link with `?unit=` opens the panel once the session is known
	$effect(() => {
		if (session.status === 'authenticated') unitPanel.sync();
	});
	// the panel resolves ids against the shared lists
	$effect(() => {
		if (unitPanel.isOpen) void lookupsStore.ensure();
	});

	// the entry form's dialogs take the entry the panel shows (an authored unit's)
	const entryOf = (id: number) => unitPanel.unit?.entries.find((e) => e.id === id);

	// The auth gate: anonymous visitors go to /login, signed-in ones leave it.
	$effect(() => {
		if (session.status === 'anonymous' && !onLogin) void goto('/login');
		if (session.status === 'authenticated' && onLogin) void goto('/ledger');
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

{#if session.status === 'authenticated' && session.user && !onLogin}
	<AppShell
		items={nav}
		footerItems={footerNav}
		currentPath={page.url.pathname}
		userName={session.user.display_name}
		onlogout={() => session.signOut()}
	>
		{@render children()}
	</AppShell>
	<PanelNavigationGuard panel={unitPanel} />
	<UnitPanelView
		panel={unitPanel}
		lookups={lookupsStore.lookups}
		locale={session.config?.locale ?? 'en'}
		onEditEntry={(id) => {
			const entry = entryOf(id);
			if (entry) entryForm.openEdit(entry);
		}}
		onDeleteEntry={(id) => {
			const entry = entryOf(id);
			if (entry) entryForm.openDelete(entry);
		}}
	/>
	<EntryFormDialogs />
	<AccountDialogs />
{:else if session.status === 'anonymous' && onLogin}
	{@render children()}
{:else if session.status === 'error' && session.error}
	<div class="grid min-h-screen place-items-center p-4">
		<ErrorState
			title="Ledgehog cannot start"
			message={session.error.message}
			onretry={() => session.start()}
		/>
	</div>
{/if}
