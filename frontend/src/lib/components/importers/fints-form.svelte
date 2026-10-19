<script lang="ts">
	import type { FintsDraft } from '#lib/importers/fints-profile.js';
	import ProfileField from './profile-field.svelte';

	// The FinTS importer's settings: four labelled fields with helper text and no placeholders. The
	// form edits the draft it is given; refusals (`errors`, by setting key) stand under their fields.
	let {
		draft,
		errors = {},
		disabled = false
	}: {
		draft: FintsDraft;
		errors?: Record<string, string>;
		disabled?: boolean;
	} = $props();
</script>

<div class="flex flex-col gap-4" data-slot="fints-form">
	<fieldset class="flex flex-col gap-4" {disabled}>
		<ProfileField
			label="Bank address"
			hint="The address your bank publishes for online access by software (FinTS). Your bank's help pages or the FinTS bank list give it. It must start with https."
			error={errors.url ?? null}
			bind:value={draft.url}
		/>
		<ProfileField
			label="Bank code"
			hint="The eight-digit Bankleitzahl of your bank."
			error={errors.bank_code ?? null}
			bind:value={draft.bankCode}
			narrow
		/>
		<ProfileField
			label="Login name"
			hint="The name you sign in to online banking with."
			error={errors.user_id ?? null}
			bind:value={draft.userId}
		/>
		<ProfileField
			label="Customer ID"
			hint="Only if your bank gave you a customer ID that differs from the login name. Leave empty otherwise."
			error={errors.customer_id ?? null}
			bind:value={draft.customerId}
		/>
	</fieldset>
	<p class="text-sm text-muted-foreground">
		The PIN is not stored. You will be asked for it whenever this login is used.
	</p>
</div>
