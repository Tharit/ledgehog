<script lang="ts">
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import { DIMENSION_COLORS, dimensionVars } from '#lib/theme/dimensions.js';
	import { iconFor, isKnownIcon } from '#lib/theme/icons.js';
	import { isKnownColor } from '#lib/theme/resolve.js';
	import { cn } from '#lib/utils.js';

	// The icon tile of a category or payee, and the popover that changes it: only the names of the
	// dimension's fixed sets (design §3, §6), plus a first choice that clears the setting so that
	// the inherited or default look applies again. Each click is a change; the popover stays open
	// so icon and colour can both be set.
	let {
		name,
		icon,
		color,
		icons,
		shownIcon,
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
		icons: readonly string[];
		/** what is drawn now: the stored look, resolved (inherited or default) */
		shownIcon: string | null;
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
		aria-label={`Change icon and colour of ${name}`}
		title="Change icon and colour"
	>
		<DimensionIcon
			icon={shownIcon}
			color={shownColor}
			initial={shownIcon === null ? initial : undefined}
			size="comfortable"
		/>
	</Popover.Trigger>
	<Popover.Content align="start" class="w-80 gap-3 p-3">
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
							ownIcon === option ? 'border-primary bg-accent' : 'border-transparent hover:bg-muted'
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
		<div class="flex flex-col gap-1.5">
			<span class="text-xs font-medium text-muted-foreground">Colour</span>
			<div class="flex flex-wrap gap-1" role="group" aria-label="Colour">
				<button
					type="button"
					class={cn(
						'h-8 rounded-md border px-2 text-xs',
						ownColor === null ? 'border-primary bg-accent' : 'border-border hover:bg-muted'
					)}
					aria-pressed={ownColor === null}
					onclick={() => onchange({ color: null })}
				>
					{clearLabel}
				</button>
				{#each DIMENSION_COLORS as option (option)}
					{@const vars = dimensionVars(option)}
					<button
						type="button"
						class={cn(
							'inline-flex size-8 items-center justify-center rounded-md border',
							ownColor === option ? 'border-primary' : 'border-transparent hover:border-border'
						)}
						aria-label={option}
						title={option}
						aria-pressed={ownColor === option}
						onclick={() => onchange({ color: option })}
					>
						<span class="size-5 rounded-sm bg-(--swatch)" style:--swatch={vars.fg}></span>
					</button>
				{/each}
			</div>
		</div>
	</Popover.Content>
</Popover.Root>
