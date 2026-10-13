<script lang="ts">
	import { DIMENSION_COLORS, dimensionVars } from '#lib/theme/dimensions.js';
	import { cn } from '#lib/utils.js';

	// The colour choices of the fixed set (design §3): a first choice that clears the setting
	// (`clearLabel`: "Inherit", "Default", "None") and one swatch per colour name. Each click is a
	// change. Shared by the look popover of a row and the add dialog of a tag.
	let {
		color,
		clearLabel,
		onchange,
		disabled = false
	}: {
		/** the stored colour name (null: none) */
		color: string | null;
		clearLabel: string;
		onchange: (color: string | null) => void;
		disabled?: boolean;
	} = $props();
</script>

<div class="flex flex-wrap gap-1" role="group" aria-label="Colour">
	<button
		type="button"
		class={cn(
			'h-8 rounded-md border px-2 text-xs',
			color === null ? 'border-primary bg-accent' : 'border-border hover:bg-muted'
		)}
		aria-pressed={color === null}
		{disabled}
		onclick={() => onchange(null)}
	>
		{clearLabel}
	</button>
	{#each DIMENSION_COLORS as option (option)}
		{@const vars = dimensionVars(option)}
		<button
			type="button"
			class={cn(
				'inline-flex size-8 items-center justify-center rounded-md border',
				color === option ? 'border-primary' : 'border-transparent hover:border-border'
			)}
			aria-label={option}
			title={option}
			aria-pressed={color === option}
			{disabled}
			onclick={() => onchange(option)}
		>
			<span class="size-5 rounded-sm bg-(--swatch)" style:--swatch={vars.fg}></span>
		</button>
	{/each}
</div>
