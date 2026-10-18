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
		/** a second line under the label, a muted one ("Syncing…"); the Sync item is the task indicator */
		status?: string;
		/** something runs behind the status: a spinner at the end of the item */
		busy?: boolean;
		/** a quiet number at the end of the item (Review); nothing at zero */
		count?: number;
	};
</script>

<script lang="ts">
	import LoaderCircleIcon from '@lucide/svelte/icons/loader-circle';
	import LogOutIcon from '@lucide/svelte/icons/log-out';
	import IconButton from './icon-button.svelte';

	// The shell: a 232px sidebar (wordmark, navigation, user) beside the content (design §5).
	// The mascot head beside the wordmark is raster for now; design §9 wants it redrawn as SVG.
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
		class="flex min-h-9 items-center gap-3 rounded-md px-2 py-1 text-sm text-sidebar-foreground hover:bg-sidebar-accent/60 aria-[current=page]:bg-sidebar-accent aria-[current=page]:font-medium"
	>
		<item.icon
			size={18}
			strokeWidth={1.75}
			class="shrink-0 text-muted-foreground"
			aria-hidden="true"
		/>
		<span class="flex min-w-0 flex-1 flex-col">
			<span>{item.label}</span>
			{#if item.status}
				<span class="truncate text-xs font-normal text-muted-foreground" data-slot="nav-status">
					{item.status}
				</span>
			{/if}
		</span>
		{#if item.count}
			<span class="shrink-0 text-xs text-muted-foreground tabular-nums" data-slot="nav-count">
				{item.count}
			</span>
		{/if}
		{#if item.busy}
			<span class="shrink-0" data-slot="nav-spinner">
				<LoaderCircleIcon
					size={14}
					strokeWidth={1.75}
					class="animate-spin text-muted-foreground"
					aria-hidden="true"
				/>
			</span>
		{/if}
	</a>
{/snippet}

<div class="flex min-h-screen">
	<aside
		class="sticky top-0 flex h-screen w-(--sidebar-width) shrink-0 flex-col border-r border-sidebar-border bg-sidebar p-4"
	>
		<div class="mb-6 flex items-center gap-2 px-2">
			<img
				src="/brand/app-icon-dark.png"
				alt=""
				width="28"
				height="28"
				class="size-7 shrink-0 object-contain"
			/>
			<p class="text-xl font-semibold text-primary">Ledgehog</p>
		</div>
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
				<IconButton verb="Log out" onclick={onlogout}>
					<LogOutIcon size={18} strokeWidth={1.75} aria-hidden="true" />
				</IconButton>
			</div>
		</div>
	</aside>
	<main class="min-w-0 flex-1 p-8">
		{@render children()}
	</main>
</div>
