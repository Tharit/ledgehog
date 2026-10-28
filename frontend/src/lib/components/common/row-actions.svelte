<script lang="ts" module>
	import type { Component } from 'svelte';

	export type RowAction = {
		/** what it does: "Rename", "Move to…", "Delete…": the tooltip and the menu item */
		verb: string;
		/** the whole accessible name of the inline button when "<verb> <name>" does not read */
		label?: string;
		/** the glyph of an inline button (a menu item has none) */
		icon?: Component<{ 'aria-hidden'?: 'true' }>;
		onselect: () => void;
		disabled?: boolean;
		/** why it is disabled, shown as the tooltip of the disabled menu item (patterns §11.4) */
		reason?: string;
		/** carries out a deletion: last in the menu, in the destructive colour */
		destructive?: boolean;
	};
</script>

<script lang="ts">
	import EllipsisIcon from '@lucide/svelte/icons/ellipsis';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.js';
	import IconButton from './icon-button.svelte';

	// The actions of one row of a settings list or a tree (patterns §11.3): at most two inline icon
	// buttons (`primary`: the edit action, then the add-in-context action), everything else in one
	// `⋯` menu with the destructive items last. Put it inside the row's element with the `group`
	// class: the controls are `opacity-0` until the row is hovered or holds focus (or a menu of the
	// row is open) and always at full opacity where there is no hover. They stay in the DOM and in
	// the tab order, hidden by opacity only.
	let {
		name,
		primary,
		menu = []
	}: {
		/** what the row is: "Food"; part of every accessible name */
		name: string;
		primary: readonly RowAction[];
		menu?: readonly RowAction[];
	} = $props();

	const inline = $derived(primary.slice(0, 2));
	// anything beyond two inline actions goes to the menu, in front of its own items
	const items = $derived.by(() => {
		const all = [...primary.slice(2), ...menu];
		return [...all.filter((a) => !a.destructive), ...all.filter((a) => a.destructive)];
	});
	const firstDestructive = $derived(items.findIndex((a) => a.destructive));
</script>

<div
	data-slot="row-actions"
	class="flex shrink-0 items-center justify-end gap-0.5 text-muted-foreground opacity-0 group-focus-within:opacity-100 group-hover:opacity-100 has-data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100"
>
	{#each inline as action (action.verb)}
		{@const Icon = action.icon}
		<IconButton
			compact
			verb={action.verb}
			{name}
			label={action.label}
			disabled={action.disabled}
			onclick={action.onselect}
		>
			{#if Icon}<Icon aria-hidden="true" />{/if}
		</IconButton>
	{/each}

	{#if items.length > 0}
		<DropdownMenu.Root>
			<DropdownMenu.Trigger>
				{#snippet child({ props })}
					<IconButton
						compact
						tooltip={false}
						verb="More actions"
						{name}
						label={`More actions for ${name}`}
						{...props}
					>
						<EllipsisIcon aria-hidden="true" />
					</IconButton>
				{/snippet}
			</DropdownMenu.Trigger>
			<DropdownMenu.Content align="end" class="min-w-44">
				{#each items as action, i (action.verb)}
					{#if i === firstDestructive && i > 0}<DropdownMenu.Separator />{/if}
					<!-- a disabled item still takes the pointer, so that its reason shows as the tooltip -->
					<DropdownMenu.Item
						variant={action.destructive ? 'destructive' : 'default'}
						disabled={action.disabled}
						onSelect={action.onselect}
						title={action.disabled ? action.reason : undefined}
						class="data-disabled:pointer-events-auto"
					>
						{action.verb}
					</DropdownMenu.Item>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>
	{/if}
</div>
