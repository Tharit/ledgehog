<script lang="ts" module>
	import type { Component, Snippet } from 'svelte';

	type IconComponent = Component<{
		size?: number;
		strokeWidth?: number;
		class?: string;
		'aria-hidden'?: 'true';
	}>;

	export type NavItem = {
		href: string;
		label: string;
		icon: IconComponent;
		/** the path an item is current under, when that is not its own address */
		match?: string;
	};
</script>

<script lang="ts">
	import LogOutIcon from '@lucide/svelte/icons/log-out';
	import { Button } from '#lib/components/ui/button/index.js';

	// The shell: a 232px sidebar (wordmark, navigation, user) beside the content (design §5).
	// The raster mascot head beside the wordmark must be redrawn as SVG first (design §9).
	let {
		items,
		footerItems = [],
		currentPath,
		userName,
		onlogout,
		children
	}: {
		items: NavItem[];
		/** navigation kept at the bottom of the sidebar (Settings), above the user */
		footerItems?: NavItem[];
		currentPath: string;
		userName: string;
		onlogout: () => void;
		children: Snippet;
	} = $props();
</script>

{#snippet link(item: NavItem)}
	{@const base = item.match ?? item.href}
	{@const active = currentPath === base || currentPath.startsWith(base + '/')}
	<a
		href={item.href}
		aria-current={active ? 'page' : undefined}
		class="flex h-9 items-center gap-3 rounded-md px-2 text-sm text-sidebar-foreground hover:bg-sidebar-accent/60 aria-[current=page]:bg-sidebar-accent aria-[current=page]:font-medium"
	>
		<item.icon size={18} strokeWidth={1.75} class="text-muted-foreground" aria-hidden="true" />
		{item.label}
	</a>
{/snippet}

<div class="flex min-h-screen">
	<aside
		class="sticky top-0 flex h-screen w-(--sidebar-width) shrink-0 flex-col border-r border-sidebar-border bg-sidebar p-4"
	>
		<p class="mb-6 px-2 text-xl font-semibold text-primary">Ledgehog</p>
		<nav aria-label="Main" class="flex flex-col gap-1">
			{#each items as item (item.href)}
				{@render link(item)}
			{/each}
		</nav>
		<div class="mt-auto flex flex-col gap-3">
			{#if footerItems.length > 0}
				<nav aria-label="Secondary" class="flex flex-col gap-1">
					{#each footerItems as item (item.href)}
						{@render link(item)}
					{/each}
				</nav>
			{/if}
			<div class="flex items-center justify-between gap-2 px-2">
				<span class="truncate text-sm" title={userName}>{userName}</span>
				<Button variant="ghost" size="icon" onclick={onlogout} aria-label="Log out" title="Log out">
					<LogOutIcon size={18} strokeWidth={1.75} aria-hidden="true" />
				</Button>
			</div>
		</div>
	</aside>
	<main class="min-w-0 flex-1 p-8">
		{@render children()}
	</main>
</div>
