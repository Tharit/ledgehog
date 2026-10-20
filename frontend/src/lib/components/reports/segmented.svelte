<script lang="ts" generics="T extends string">
	import { Button } from '#lib/components/ui/button/index.js';

	// A short fixed choice shown as a row of buttons (the kind, the step, the mode of a report): the
	// chosen one is pressed. The choice is in the address, so each press is a navigation.
	let {
		label,
		options,
		value,
		onchange
	}: {
		/** the group's accessible name */
		label: string;
		options: readonly { value: T; label: string }[];
		value: T;
		onchange: (value: T) => void;
	} = $props();
</script>

<div class="inline-flex gap-1" role="group" aria-label={label} data-slot="segmented">
	{#each options as option (option.value)}
		<Button
			variant={option.value === value ? 'secondary' : 'outline'}
			aria-pressed={option.value === value}
			onclick={() => onchange(option.value)}>{option.label}</Button
		>
	{/each}
</div>
