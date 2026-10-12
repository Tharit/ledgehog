<script lang="ts">
	import './layout.css';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import ListIcon from '@lucide/svelte/icons/list';
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import favicon from '#lib/assets/favicon.svg';
	import AppShell, { type NavItem } from '#lib/components/common/app-shell.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import { session } from '#lib/stores/session.svelte.js';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	// Only routes that exist (design §10).
	const nav: NavItem[] = [{ href: '/ledger', label: 'Ledger', icon: ListIcon }];
	// at the bottom of the sidebar, as in the mockup (design §5); /settings opens its first tab
	const footerNav: NavItem[] = [
		{ href: '/settings', label: 'Settings', icon: SettingsIcon, match: '/settings' }
	];

	const onLogin = $derived(page.url.pathname === '/login');

	onMount(() => {
		void session.start();
	});

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
