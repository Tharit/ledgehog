<script lang="ts">
	import EllipsisIcon from '@lucide/svelte/icons/ellipsis';
	import IconButton from '#lib/components/common/icon-button.svelte';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.js';

	// The ledger's secondary actions, drawn in the page header before "Add entry": the `⋯` menu with
	// "Export CSV…" (patterns §11.3), which asks before it downloads.
	let { onexport }: { onexport: () => void } = $props();
</script>

<DropdownMenu.Root>
	<DropdownMenu.Trigger>
		{#snippet child({ props })}
			<IconButton
				tooltip={false}
				verb="More actions"
				name="the ledger"
				label="More actions for the ledger"
				{...props}
			>
				<EllipsisIcon aria-hidden="true" />
			</IconButton>
		{/snippet}
	</DropdownMenu.Trigger>
	<DropdownMenu.Content align="end" class="min-w-44">
		<DropdownMenu.Item onSelect={onexport}>Export CSV…</DropdownMenu.Item>
	</DropdownMenu.Content>
</DropdownMenu.Root>
