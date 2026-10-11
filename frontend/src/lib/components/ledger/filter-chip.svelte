<script lang="ts">
	import type { Snippet } from 'svelte';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import { cn } from '#lib/utils.js';

	// A pill that opens a popover: the shell every filter chip shares. An active chip is tinted
	// and shows what it filters by; an inactive one shows the dimension's name ("All accounts").
	let {
		label,
		active = false,
		open = $bindable(false),
		width = 'w-72',
		children
	}: {
		label: string;
		active?: boolean;
		open?: boolean;
		width?: string;
		children: Snippet;
	} = $props();
</script>

<Popover.Root bind:open>
	<Popover.Trigger
		class={cn(
			'inline-flex h-8 max-w-56 items-center gap-1.5 rounded-full border px-3 text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-ring',
			active
				? 'border-primary/40 bg-accent font-medium text-foreground'
				: 'border-border bg-muted text-muted-foreground hover:text-foreground'
		)}
	>
		<span class="truncate">{label}</span>
		<ChevronDownIcon size={14} strokeWidth={1.75} class="shrink-0" aria-hidden="true" />
	</Popover.Trigger>
	<Popover.Content align="start" class={cn(width, 'gap-2 p-3')}>
		{@render children()}
	</Popover.Content>
</Popover.Root>
