<script lang="ts">
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import { Button } from '#lib/components/ui/button/index.js';

	// The chevron of a row that folds its children (the category tree in Settings, the groups of
	// the report tables): "Expand X" / "Collapse X". A row with nothing below it keeps the width as
	// a spacer, so the names line up.
	let {
		name,
		expanded,
		toggleable = true,
		ontoggle
	}: {
		name: string;
		expanded: boolean;
		/** false: nothing to fold, only the spacer */
		toggleable?: boolean;
		ontoggle: () => void;
	} = $props();
</script>

{#if toggleable}
	<Button
		variant="ghost"
		size="icon-xs"
		aria-label={expanded ? `Collapse ${name}` : `Expand ${name}`}
		aria-expanded={expanded}
		onclick={ontoggle}
	>
		{#if expanded}<ChevronDownIcon aria-hidden="true" />{:else}<ChevronRightIcon
				aria-hidden="true"
			/>{/if}
	</Button>
{:else}
	<span class="size-6 shrink-0" aria-hidden="true"></span>
{/if}
