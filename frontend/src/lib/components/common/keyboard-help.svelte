<script lang="ts" module>
	/** One line of the help: the keys as they are written, and what they do. */
	export type HelpItem = { keys: string; description: string };
	/** A titled group of lines; a screen with few shortcuts needs only one, untitled. */
	export type HelpGroup = { title?: string; items: readonly HelpItem[] };

	// keys typed into a field, or inside an open dialog or popover, belong to that surface
	const OWNS_KEYS =
		'input, textarea, select, [contenteditable], [role="dialog"], [data-slot="popover-content"]';
	const IN_FIELD = 'input, textarea, select, [contenteditable]';
</script>

<script lang="ts">
	import { cn } from '#lib/utils.js';

	// The keyboard help of every screen (patterns §5): a quiet "Keyboard shortcuts (?)" button and,
	// when open, a panel fixed to the corner of the view (not a dialog) listing the screen's
	// shortcuts in groups. It scrolls when long. `?` shows or hides it and Esc hides it, on a list
	// page (`page`: keys typed in a field or inside the work panel are not ours) and inside the
	// work panel (`panel`: only keys typed inside it are), so the panel's `?` and the list's never
	// clash. Each screen supplies its own groups.
	let {
		groups,
		open = $bindable(false),
		scope = 'page',
		class: className
	}: {
		groups: readonly HelpGroup[];
		open?: boolean;
		scope?: 'page' | 'panel';
		/** classes of the trigger */
		class?: string;
	} = $props();

	function ours(target: EventTarget | null): boolean {
		if (!(target instanceof Element)) return scope === 'page';
		return scope === 'panel'
			? target.closest('[data-slot="unit-panel"]') !== null && target.closest(IN_FIELD) === null
			: target.closest(OWNS_KEYS) === null;
	}

	// in the capture phase, so that Esc closes the help ALONE: the list behind and the panel's own
	// Esc never see the key that closed it
	function onkeydown(event: KeyboardEvent) {
		if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
		if (!ours(event.target)) return;
		if (event.key === '?') {
			event.preventDefault();
			open = !open;
		} else if (event.key === 'Escape' && open) {
			event.preventDefault();
			event.stopPropagation();
			open = false;
		}
	}
</script>

<svelte:window onkeydowncapture={onkeydown} />

<button
	type="button"
	class={cn('underline-offset-2 hover:underline', className)}
	onclick={() => (open = !open)}
	aria-expanded={open}
>
	Keyboard shortcuts (?)
</button>

{#if open}
	<div
		role="region"
		aria-label="Keyboard shortcuts"
		data-slot="keyboard-help"
		class="fixed right-4 bottom-4 z-50 flex max-h-[min(70vh,32rem)] w-80 max-w-[calc(100vw-2rem)] flex-col gap-3 overflow-y-auto rounded-xl border bg-popover p-4 text-sm text-popover-foreground shadow-md"
	>
		<h2 class="text-base font-semibold">Keyboard</h2>
		{#each groups as group, i (i)}
			<div class="flex flex-col gap-1">
				{#if group.title}
					<h3 class="text-xs font-medium text-muted-foreground">{group.title}</h3>
				{/if}
				<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
					{#each group.items as item (item.keys)}
						<dt>
							<kbd class="rounded-sm bg-muted px-1.5 py-0.5 font-mono text-xs">{item.keys}</kbd>
						</dt>
						<dd class="text-muted-foreground">{item.description}</dd>
					{/each}
				</dl>
			</div>
		{/each}
	</div>
{/if}
