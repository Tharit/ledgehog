<script lang="ts">
	import { hasSettingsForm } from '#lib/importers/forms.js';
	import type { CsvDraft } from '#lib/importers/csv-profile.js';
	import CsvProfileForm from './csv-profile-form.svelte';

	// The importer's own settings: one form component per importer, chosen by its name, like the
	// provenance widget (ux/views/importers.md; patterns §4.5). Only the CSV importer has one so far.
	let {
		importer,
		draft,
		errors = {},
		disabled = false
	}: {
		importer: string;
		draft: CsvDraft;
		errors?: Record<string, string>;
		disabled?: boolean;
	} = $props();
</script>

{#if importer === 'csv'}
	<CsvProfileForm {draft} {errors} {disabled} />
{:else if !hasSettingsForm(importer)}
	<p class="text-sm text-muted-foreground">
		The importer “{importer}” has no settings form yet.
	</p>
{/if}
