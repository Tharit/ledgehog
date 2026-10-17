<script lang="ts">
	import ActionDialog from '#lib/components/common/action-dialog.svelte';
	import AccountSelect from '#lib/components/common/account-select.svelte';
	import Field from '#lib/components/common/field.svelte';
	import { formatCount, formatDateRange } from '#lib/format/index.js';
	import type { LinkAccountFlow } from '#lib/importers/link-flow.svelte.js';
	import type { Account } from '#lib/types/domain.js';

	// "Link account": a form dialog (ux/views/importers.md; patterns §11.2). An account picker over the
	// open accounts the instance does not link yet and, for a file importer, nothing else: it is never
	// asked for a reference. Once an account is chosen the dialog shows the link's dry run, the
	// warning of spec §5.4. The verb is "Link".
	let {
		flow,
		accounts,
		locale = 'en'
	}: { flow: LinkAccountFlow; accounts: readonly Account[]; locale?: string } = $props();

	const preview = $derived(flow.preview);
	const rows = $derived(preview?.user_authored_count ?? 0);
</script>

<ActionDialog
	open={flow.open}
	onclose={() => flow.close()}
	title={`Link an account to “${flow.instance?.label ?? ''}”`}
	description="Uploads of this format go to the account you choose."
	verb="Link"
	busyVerb="Linking…"
	busy={flow.busy}
	disabled={!flow.canLink}
	onsubmit={() => void flow.confirm()}
	feedback={flow.error ? { kind: 'error', text: flow.error } : null}
>
	<Field
		label="Account"
		hint={accounts.length === 0 ? 'Every open account is linked already.' : undefined}
	>
		{#snippet children(control)}
			<AccountSelect
				{...control}
				{accounts}
				label="Account"
				value={flow.accountId}
				disabled={flow.busy}
				onchange={(id) => void flow.choose(id)}
			/>
		{/snippet}
	</Field>

	{#if flow.checking}
		<p class="text-muted-foreground" aria-busy="true">Checking what linking would do…</p>
	{:else if preview}
		<div class="flex flex-col gap-1" data-slot="link-preview">
			{#if rows > 0 && preview.first_booked_on && preview.last_booked_on}
				<p>
					This account holds {formatCount(rows, locale)}
					{rows === 1 ? 'row' : 'rows'} entered by hand, {formatDateRange(
						preview.first_booked_on,
						preview.last_booked_on,
						locale
					)}.
				</p>
				<p>Imports overlapping them are not deduplicated against them.</p>
			{/if}
			{#if preview.account_becomes_synced}
				<p>Once linked, the account is synced: rows can no longer be entered by hand.</p>
			{/if}
		</div>
	{/if}
</ActionDialog>
