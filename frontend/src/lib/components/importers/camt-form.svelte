<script lang="ts">
	import type { FormProps } from '#lib/importers/forms.js';

	// The camt importer has no settings (plugins/importers/camt.md §1): the page holds the label, this
	// line and the linked accounts. The file says which format it is. The registry hands every form its
	// draft, errors and disabled flag; this one has only the last to mention.
	let { disabled = false }: FormProps<Record<string, never>> = $props();
</script>

<p
	class="text-sm text-muted-foreground"
	data-slot="camt-form"
	aria-disabled={disabled || undefined}
>
	Reads the bank’s XML statement export. The file says which format it is; there is nothing to set
	up.
</p>
