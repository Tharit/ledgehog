<script lang="ts">
	import { entryForm } from '#lib/entry-form/controller.svelte.js';
	import AddEntryDialog from './add-entry-dialog.svelte';
	import DeleteEntryDialog from './delete-entry-dialog.svelte';
	import EditEntryDialog from './edit-entry-dialog.svelte';

	// The entry form's three dialogs, mounted once in the root layout and opened by the controller.
</script>

<AddEntryDialog
	open={entryForm.mode === 'add'}
	options={entryForm.addOptions}
	onclose={() => entryForm.close()}
/>
<EditEntryDialog
	open={entryForm.mode === 'edit'}
	target={entryForm.target}
	onclose={() => entryForm.close()}
/>
<DeleteEntryDialog
	open={entryForm.mode === 'delete'}
	target={entryForm.target}
	onclose={() => entryForm.close()}
/>
