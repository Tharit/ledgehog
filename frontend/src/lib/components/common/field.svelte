<script lang="ts">
	import type { Snippet } from 'svelte';

	// A labelled control (patterns §11.4, §11.5): visible label above, an optional hint, and the
	// validation message under the field (red: the destructive token, design §2). It wires the
	// control: the snippet receives `id`, `aria-describedby` and `aria-invalid` to spread onto it.
	// `group` makes it a fieldset with a legend, for radio choices.
	type ControlProps = {
		id: string;
		'aria-describedby': string | undefined;
		'aria-invalid': boolean;
	};

	let {
		label,
		hint,
		error = null,
		group = false,
		children
	}: {
		label: string;
		hint?: string;
		error?: string | null;
		group?: boolean;
		children: Snippet<[ControlProps]>;
	} = $props();

	const uid = $props.id();
	const hintId = $derived(hint ? `${uid}-hint` : undefined);
	const errorId = $derived(error ? `${uid}-error` : undefined);
	const control = $derived<ControlProps>({
		id: uid,
		'aria-describedby': [hintId, errorId].filter(Boolean).join(' ') || undefined,
		'aria-invalid': error !== null && error !== ''
	});
</script>

{#snippet lines()}
	{#if hint}<p id={hintId} class="text-xs text-muted-foreground">{hint}</p>{/if}
	{#if error}<p id={errorId} role="alert" class="text-xs text-destructive">{error}</p>{/if}
{/snippet}

{#if group}
	<fieldset
		class="flex flex-col gap-1.5"
		data-slot="field"
		aria-describedby={control['aria-describedby']}
	>
		<legend class="mb-1.5 text-sm font-medium">{label}</legend>
		{@render children(control)}
		{@render lines()}
	</fieldset>
{:else}
	<div class="flex flex-col gap-1.5" data-slot="field">
		<label for={uid} class="text-sm font-medium">{label}</label>
		{@render children(control)}
		{@render lines()}
	</div>
{/if}
