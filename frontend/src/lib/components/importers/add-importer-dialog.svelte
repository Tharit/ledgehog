<script lang="ts">
	import ActionDialog from '#lib/components/common/action-dialog.svelte';
	import Picker, { type PickerItem } from '#lib/components/common/picker.svelte';
	import { hasSettingsForm } from '#lib/importers/forms.js';
	import { kindText } from '#lib/importers/list.js';
	import type { CatalogEntry } from '#lib/types/domain.js';

	// "Add importer": a pick dialog over the importer catalog (ux/views/importers.md; patterns
	// §11.2). Each importer by name, with whether it takes a file or fetches. Choosing one is the
	// whole action: it opens the add page for it. An importer without a setup form yet is shown with
	// the reason it cannot be chosen.
	let {
		open,
		catalog,
		onclose,
		onpick
	}: {
		open: boolean;
		catalog: readonly CatalogEntry[];
		onclose: () => void;
		onpick: (name: string) => void;
	} = $props();

	const items = $derived<PickerItem[]>(
		catalog.map((entry, id) => ({
			id,
			label: `${entry.name} — ${kindText(entry.kind)}`,
			disabled: hasSettingsForm(entry.name) ? undefined : 'no setup form for it yet'
		}))
	);

	function choose(id: number) {
		const entry = catalog[id];
		if (entry) onpick(entry.name);
	}
</script>

<ActionDialog
	{open}
	{onclose}
	title="Add importer"
	description="Choose what the importer reads."
	mode="pick"
>
	<Picker
		{items}
		label="importers"
		placeholder="Find an importer…"
		emptyText="This deployment registers no importer."
		onselect={choose}
	/>
</ActionDialog>
