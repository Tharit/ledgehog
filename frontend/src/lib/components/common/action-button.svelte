<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Button, type ButtonProps } from '#lib/components/ui/button/index.js';
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';

	// The text button of every surface (patterns §11.4, design §5 "Controls"): one height (the
	// default 32px), a verb and no icon. The variants are the roles: `primary` finishes a surface,
	// `outline` is Cancel and the secondary actions, `destructive` carries out a deletion, `ghost`
	// and `link` are helpers. While `busy` it is disabled and says what it is doing (`busyLabel`:
	// "Saving…"); a disabled action may say why (`reason`, as a tooltip).
	let {
		variant = 'primary',
		busy = false,
		busyLabel,
		reason,
		disabled = false,
		children,
		...rest
	}: Omit<ButtonProps, 'variant' | 'size' | 'children' | 'disabled'> & {
		variant?: 'primary' | 'secondary' | 'outline' | 'destructive' | 'ghost' | 'link';
		busy?: boolean;
		busyLabel?: string;
		/** why the action is disabled, shown as a tooltip */
		reason?: string;
		disabled?: boolean;
		children: Snippet;
	} = $props();
</script>

{#snippet button()}
	<Button
		variant={variant === 'primary' ? 'default' : variant}
		disabled={disabled || busy}
		aria-busy={busy || undefined}
		{...rest}
	>
		{#if busy && busyLabel}{busyLabel}{:else}{@render children()}{/if}
	</Button>
{/snippet}

{#if reason && disabled}
	<Tooltip.Provider>
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<span {...props} class="inline-flex">{@render button()}</span>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content>{reason}</Tooltip.Content>
		</Tooltip.Root>
	</Tooltip.Provider>
{:else}
	{@render button()}
{/if}
