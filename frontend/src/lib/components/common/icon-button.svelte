<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Button, type ButtonProps } from '#lib/components/ui/button/index.js';
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';

	// The icon-only button of rows and headers (patterns §11.3). Its accessible name is
	// "<Verb> <name>" ("Rename Food") and its tooltip the verb ("Rename"): the same words as the
	// menu item it may sit beside. 32px, 24px (`compact`) inside a row (design §5). `tooltip={false}`
	// is for a trigger that already carries another Bits behaviour (the `⋯` menu).
	let {
		verb,
		name = '',
		label,
		compact = false,
		tooltip = true,
		onclick,
		children,
		...rest
	}: Omit<ButtonProps, 'variant' | 'size' | 'children' | 'aria-label'> & {
		/** what it does: "Rename", "Edit" */
		verb: string;
		/** what it does it to: "Food"; absent for a control that acts on nothing in particular */
		name?: string;
		/** the whole accessible name when "<verb> <name>" does not read ("Add subcategory to Food") */
		label?: string;
		compact?: boolean;
		tooltip?: boolean;
		children: Snippet;
	} = $props();

	const accessibleName = $derived(label ?? `${verb} ${name}`.trim());
	const size = $derived(compact ? 'icon-xs' : 'icon');
</script>

{#if tooltip}
	<Tooltip.Provider>
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<Button
						variant="ghost"
						{size}
						{...props}
						{...rest}
						aria-label={accessibleName}
						onclick={(event: MouseEvent) => {
							(props.onclick as ((e: MouseEvent) => void) | undefined)?.(event);
							(onclick as ((e: MouseEvent) => void) | null | undefined)?.(event);
						}}
					>
						{@render children()}
					</Button>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content>{verb}</Tooltip.Content>
		</Tooltip.Root>
	</Tooltip.Provider>
{:else}
	<Button variant="ghost" {size} {...rest} aria-label={accessibleName} {onclick}>
		{@render children()}
	</Button>
{/if}
