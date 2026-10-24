<script lang="ts">
	import ChoiceSelect from '#lib/components/common/choice-select.svelte';
	import DateField from '#lib/components/common/date-field.svelte';
	import Field from '#lib/components/common/field.svelte';
	import type { EmailDraft } from '#lib/importers/email-profile.js';
	import { session } from '#lib/stores/session.svelte.js';
	import ProfileField from './profile-field.svelte';

	// The email importer's settings (ux/views/importers.md "The email form"): labelled fields with
	// helper text and no placeholders, the senders one address per line. The form edits the draft it is
	// given; refusals (`errors`, by setting key) stand under their fields. The password is no field:
	// it is asked whenever the login is used.
	let {
		draft,
		errors = {},
		disabled = false
	}: {
		draft: EmailDraft;
		errors?: Record<string, string>;
		disabled?: boolean;
	} = $props();
</script>

<div class="flex flex-col gap-4" data-slot="email-form">
	<fieldset class="flex flex-col gap-4" {disabled}>
		<ProfileField
			label="Mail server"
			hint="The IMAP server of the mailbox the receipts are forwarded to."
			error={errors.host ?? null}
			bind:value={draft.host}
		/>
		<Field
			label="Security"
			hint="TLS is the usual choice. There is no unencrypted connection."
			error={errors.security ?? null}
		>
			{#snippet children(control)}
				<ChoiceSelect
					{...control}
					label="Security"
					value={draft.security}
					options={[
						{ value: 'tls', label: 'TLS' },
						{ value: 'starttls', label: 'STARTTLS' }
					]}
					{disabled}
					onchange={(next) => (draft.security = next === 'starttls' ? 'starttls' : 'tls')}
				/>
			{/snippet}
		</Field>
		<ProfileField
			label="Port"
			hint="Leave empty for the usual port: 993 with TLS, 143 with STARTTLS."
			error={errors.port ?? null}
			bind:value={draft.port}
			narrow
		/>
		<ProfileField
			label="Login name"
			hint="The name you sign in to the mailbox with."
			error={errors.username ?? null}
			bind:value={draft.username}
		/>
		<ProfileField
			label="Folder"
			hint="The folder the receipts arrive in."
			error={errors.mailbox ?? null}
			bind:value={draft.mailbox}
		/>
		<ProfileField
			label="Senders"
			hint="One address per line. Mail is read only when it comes from one of these addresses or was forwarded by one. This keeps other mail out; it is not a security check."
			error={errors.senders ?? null}
			bind:value={draft.senders}
			multiline
		/>
		<Field
			label="Start date"
			hint="No receipt dated before it is imported."
			error={errors.start_date ?? null}
		>
			{#snippet children(control)}
				<DateField
					{...control}
					label="Start date"
					bind:value={draft.startDate}
					locale={session.config?.locale}
					{disabled}
				/>
			{/snippet}
		</Field>
	</fieldset>
	<p class="text-sm text-muted-foreground">
		The password is not stored. You will be asked for it whenever this login is used. Where your
		provider offers app passwords, use one.
	</p>
	<p class="text-sm text-muted-foreground" data-slot="email-privacy">
		Every message read is sent whole to the configured model, names and addresses included.
	</p>
</div>
