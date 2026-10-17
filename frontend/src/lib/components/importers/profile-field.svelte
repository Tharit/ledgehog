<script lang="ts">
	import Field from '#lib/components/common/field.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import { Textarea } from '#lib/components/ui/textarea/index.js';

	// One text setting of a profile: a visible label, the helper text that stands in for an example
	// (no field carries a placeholder, patterns §11.4) and the server's refusal under the field.
	// `multiline` is a list with one item per line.
	let {
		label,
		hint,
		error = null,
		value = $bindable(''),
		multiline = false,
		disabled = false,
		narrow = false
	}: {
		label: string;
		hint?: string;
		error?: string | null;
		value?: string;
		multiline?: boolean;
		disabled?: boolean;
		/** a short value: a single character, a number */
		narrow?: boolean;
	} = $props();
</script>

<Field {label} {hint} {error}>
	{#snippet children(control)}
		{#if multiline}
			<Textarea {...control} bind:value rows={3} {disabled} autocomplete="off" spellcheck={false} />
		{:else}
			<Input
				{...control}
				bind:value
				{disabled}
				class={narrow ? 'w-28' : undefined}
				autocomplete="off"
				spellcheck={false}
			/>
		{/if}
	{/snippet}
</Field>
