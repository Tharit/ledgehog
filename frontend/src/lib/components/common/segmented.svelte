<script lang="ts" generics="T">
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';
	import { cn } from '#lib/utils.js';

	// A choice among a few (design §5): one 32px box split into segments, the chosen one filled
	// `primary`. As a `group` the segments are pressed buttons (a report's kind, step, mode; an
	// entry's type); as a `radio` group they are radios (a filter's direction, link state). A
	// disabled segment may say why (`reason`, as a tooltip).
	let {
		label,
		options,
		value,
		onchange,
		role = 'group',
		class: className
	}: {
		/** the group's accessible name */
		label: string;
		options: readonly { value: T; label: string; disabled?: boolean; reason?: string }[];
		value: T;
		onchange: (value: T) => void;
		role?: 'group' | 'radio';
		class?: string;
	} = $props();
</script>

{#snippet segment(option: (typeof options)[number])}
	{@const chosen = option.value === value}
	<button
		type="button"
		role={role === 'radio' ? 'radio' : undefined}
		aria-checked={role === 'radio' ? chosen : undefined}
		aria-pressed={role === 'radio' ? undefined : chosen}
		disabled={option.disabled}
		data-chosen={chosen}
		class={cn(
			'h-full px-3 text-sm font-medium whitespace-nowrap outline-none select-none',
			'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
			'disabled:opacity-50',
			chosen ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'
		)}
		onclick={() => onchange(option.value)}>{option.label}</button
	>
{/snippet}

<div
	class={cn(
		'inline-flex h-8 divide-x divide-border overflow-hidden rounded-md border border-border',
		className
	)}
	role={role === 'radio' ? 'radiogroup' : 'group'}
	aria-label={label}
	data-slot="segmented"
>
	{#each options as option (option.label)}
		{#if option.disabled && option.reason}
			<Tooltip.Provider>
				<Tooltip.Root>
					<Tooltip.Trigger>
						{#snippet child({ props })}
							<span {...props} class="inline-flex">{@render segment(option)}</span>
						{/snippet}
					</Tooltip.Trigger>
					<Tooltip.Content>{option.reason}</Tooltip.Content>
				</Tooltip.Root>
			</Tooltip.Provider>
		{:else}
			{@render segment(option)}
		{/if}
	{/each}
</div>
