<script lang="ts">
	import XIcon from '@lucide/svelte/icons/x';
	import { Input } from '#lib/components/ui/input/index.js';

	// A clearance account's providers, typed or picked like tags (patterns §6) but creating nothing:
	// the known providers are suggested, any value is accepted, trimmed, once. Enter, a comma or
	// leaving the box adds what is typed; each chip has a remove X. Spread the Field's control
	// props onto it.
	let {
		providers = $bindable([]),
		suggestions = [],
		disabled = false,
		...control
	}: {
		providers?: string[];
		/** the providers the document importers know */
		suggestions?: readonly string[];
		disabled?: boolean;
		id?: string;
		'aria-describedby'?: string;
		'aria-invalid'?: boolean;
	} = $props();

	const uid = $props.id();
	let draft = $state('');
	const offered = $derived(suggestions.filter((name) => !providers.includes(name)));

	function add() {
		const name = draft.trim();
		draft = '';
		if (name === '' || providers.includes(name)) return;
		providers = [...providers, name];
	}

	function onkeydown(event: KeyboardEvent) {
		// an Enter on an empty box is the dialog's: it submits
		if ((event.key === 'Enter' && draft.trim() !== '') || event.key === ',') {
			event.preventDefault();
			add();
		} else if (event.key === 'Backspace' && draft === '' && providers.length > 0) {
			providers = providers.slice(0, -1);
		}
	}
</script>

<div class="flex flex-col gap-1.5" data-slot="provider-field">
	{#if providers.length > 0}
		<ul class="flex flex-wrap gap-1" aria-label="Providers">
			{#each providers as name (name)}
				<li
					class="inline-flex h-6 items-center gap-0.5 rounded-sm bg-muted pr-0.5 pl-2 text-xs font-medium"
				>
					<span>{name}</span>
					<button
						type="button"
						class="inline-flex size-5 items-center justify-center rounded-sm outline-none hover:bg-black/10 focus-visible:ring-2 focus-visible:ring-ring/50"
						aria-label={`Remove provider ${name}`}
						title={`Remove provider ${name}`}
						{disabled}
						onclick={() => (providers = providers.filter((p) => p !== name))}
					>
						<XIcon size={12} aria-hidden="true" />
					</button>
				</li>
			{/each}
		</ul>
	{/if}
	<Input
		bind:value={draft}
		{...control}
		{disabled}
		autocomplete="off"
		list={`${uid}-suggestions`}
		{onkeydown}
		onblur={add}
	/>
	<datalist id={`${uid}-suggestions`}>
		{#each offered as name (name)}<option value={name}></option>{/each}
	</datalist>
</div>
