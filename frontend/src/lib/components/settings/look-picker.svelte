<script lang="ts">
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import { dimensionVars } from '#lib/theme/dimensions.js';
	import { iconFor, isKnownIcon } from '#lib/theme/icons.js';
	import { isKnownColor } from '#lib/theme/resolve.js';
	import { cn } from '#lib/utils.js';
	import ColorChoices from './color-choices.svelte';

	// The icon tile of a category or payee (a tag has no icon: a colour dot, colour choices only), and the popover that changes it: only the names of the
	// dimension's fixed sets (design §3, §6), plus a first choice that clears the setting so that
	// the inherited or default look applies again. Each click is a change; the popover stays open
	// so icon and colour can both be set.
	let {
		name,
		icon,
		color,
		icons,
		shownIcon = null,
		shownColor,
		initial,
		clearLabel,
		onchange
	}: {
		/** what the look belongs to, for the labels */
		name: string;
		/** the stored values (null: none) */
		icon: string | null;
		color: string | null;
		/** the names this dimension's editor offers */
		icons?: readonly string[];
		/** what is drawn now: the stored look, resolved (inherited or default) */
		shownIcon?: string | null;
		shownColor: string;
		/** stands in for the icon when it is null (a payee) */
		initial?: string;
		/** the choice that clears a setting: "Inherit" or "Default" */
		clearLabel: string;
		onchange: (patch: { icon?: string | null; color?: string | null }) => void;
	} = $props();

	const ownIcon = $derived(isKnownIcon(icon) ? icon : null);
	const ownColor = $derived(isKnownColor(color) ? color : null);
</script>

<Popover.Root>
	<Popover.Trigger
		class="inline-flex rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
		aria-label={icons ? `Change icon and colour of ${name}` : `Change colour of ${name}`}
		title={icons ? 'Change icon and colour' : 'Change colour'}
	>
		{#if icons}
			<DimensionIcon
				icon={shownIcon}
				color={shownColor}
				initial={shownIcon === null ? initial : undefined}
				size="comfortable"
			/>
		{:else}
			<span class="inline-flex size-8 items-center justify-center" aria-hidden="true">
				<span
					class="size-3.5 rounded-full bg-(--swatch)"
					style:--swatch={dimensionVars(shownColor).fg}
				></span>
			</span>
		{/if}
	</Popover.Trigger>
	<Popover.Content align="start" class="w-80 gap-3 p-3">
		{#if icons}
			<div class="flex flex-col gap-1.5">
				<span class="text-xs font-medium text-muted-foreground">Icon</span>
				<div class="flex flex-wrap gap-1" role="group" aria-label="Icon">
					<button
						type="button"
						class={cn(
							'h-8 rounded-md border px-2 text-xs',
							ownIcon === null ? 'border-primary bg-accent' : 'border-border hover:bg-muted'
						)}
						aria-pressed={ownIcon === null}
						onclick={() => onchange({ icon: null })}
					>
						{clearLabel}
					</button>
					{#each icons as option (option)}
						{@const Icon = iconFor(option)}
						<button
							type="button"
							class={cn(
								'inline-flex size-8 items-center justify-center rounded-md border',
								ownIcon === option
									? 'border-primary bg-accent'
									: 'border-transparent hover:bg-muted'
							)}
							aria-label={option}
							title={option}
							aria-pressed={ownIcon === option}
							onclick={() => onchange({ icon: option })}
						>
							<Icon size={16} strokeWidth={1.75} aria-hidden="true" />
						</button>
					{/each}
				</div>
			</div>
		{/if}
		<div class="flex flex-col gap-1.5">
			<span class="text-xs font-medium text-muted-foreground">Colour</span>
			<ColorChoices color={ownColor} {clearLabel} onchange={(color) => onchange({ color })} />
		</div>
	</Popover.Content>
</Popover.Root>
