<script lang="ts">
	import { settingsFormOf, type AnyDraft } from '#lib/importers/forms.js';

	// The importer's own settings: one form component per importer, chosen by its name through the
	// registry, like the provenance widget (ux/views/importers.md; patterns §4.5).
	let {
		importer,
		draft,
		errors = {},
		disabled = false
	}: {
		importer: string;
		draft: AnyDraft;
		errors?: Record<string, string>;
		disabled?: boolean;
	} = $props();

	const form = $derived(settingsFormOf(importer));
	const Form = $derived(form?.component);
</script>

{#if Form}
	<Form {draft} {errors} {disabled} />
{:else}
	<p class="text-sm text-muted-foreground">
		The importer “{importer}” has no settings form yet.
	</p>
{/if}
