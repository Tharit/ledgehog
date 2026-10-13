<script lang="ts">
	import { untrack } from 'svelte';
	import { Input } from '#lib/components/ui/input/index.js';

	// In-place edit of one text value where it is shown (patterns §11.2): the only inline form.
	// Mount it to start editing and unmount it on `ondone` / `oncancel`. Enter commits; Esc cancels;
	// leaving the field commits a changed, non-empty value and cancels an unchanged or empty one,
	// so a typed name is never lost silently. `onsave` answers with the refusal to show under the
	// field (the edit then stays open) or `null` when the value is saved.
	let {
		value,
		label,
		onsave,
		ondone,
		oncancel
	}: {
		value: string;
		/** the field's accessible name: "Name of Food" */
		label: string;
		onsave: (value: string) => Promise<string | null> | string | null;
		ondone: () => void;
		oncancel: () => void;
	} = $props();

	let draft = $state(untrack(() => value));
	let error = $state<string | null>(null);
	let busy = $state(false);
	let settled = false;
	let input = $state<HTMLInputElement | null>(null);

	$effect(() => {
		input?.focus();
		input?.select();
	});

	const errorId = $props.id();

	function cancel() {
		if (settled || busy) return;
		settled = true;
		oncancel();
	}

	async function commit() {
		if (settled || busy) return;
		const next = draft.trim();
		if (next === '' || next === value) {
			cancel();
			return;
		}
		busy = true;
		error = await onsave(next);
		busy = false;
		if (error === null) {
			settled = true;
			ondone();
		}
	}

	function keydown(event: KeyboardEvent) {
		if (event.key === 'Enter') {
			event.preventDefault();
			void commit();
		} else if (event.key === 'Escape') {
			event.preventDefault();
			event.stopPropagation();
			cancel();
		}
	}
</script>

<div class="flex min-w-0 flex-col gap-1" data-slot="inline-edit">
	<Input
		bind:ref={input}
		bind:value={draft}
		aria-label={label}
		aria-invalid={error !== null}
		aria-describedby={error !== null ? errorId : undefined}
		readonly={busy}
		oninput={() => (error = null)}
		onkeydown={keydown}
		onblur={() => void commit()}
	/>
	{#if error}
		<span id={errorId} role="alert" class="text-xs text-destructive">{error}</span>
	{/if}
</div>
