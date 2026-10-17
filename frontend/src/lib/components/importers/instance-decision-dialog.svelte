<script lang="ts">
	import ActionDialog from '#lib/components/common/action-dialog.svelte';
	import type { InstanceDecisionFlow } from '#lib/importers/decision-flow.svelte.js';
	import type { Lookups } from '#lib/ledger/lookups.js';

	// Delete…, Reset… and Unlink… of an importer instance: a decision dialog (patterns §11.2) that
	// says what the action does and what it leaves (ux/views/importers.md). The server's refusal, an
	// instance that has runs for one, stands above the buttons as an error with its pointer.
	let { flow, lookups }: { flow: InstanceDecisionFlow; lookups: Lookups } = $props();

	const label = $derived(flow.instance?.label ?? '');
	const account = $derived(
		flow.accountId === null
			? 'the account'
			: (lookups.accounts.get(flow.accountId)?.name ?? `account #${flow.accountId}`)
	);
	const copy = $derived.by(() => {
		switch (flow.kind) {
			case 'delete':
				return {
					title: `Delete the importer “${label}”?`,
					description:
						'Its links go with it, and so does being synced for an account that only it fed. The rows it imported are not touched.',
					verb: 'Delete',
					busy: 'Deleting…',
					destructive: true
				};
			case 'reset':
				return {
					title: `Reset the importer “${label}”?`,
					description: 'This clears what the importer remembers between runs. Its settings stay.',
					verb: 'Reset',
					busy: 'Resetting…',
					destructive: false
				};
			default:
				return {
					title: `Unlink ${account} from “${label}”?`,
					description:
						'The account’s coverage stays as history, and the rows it holds stay. If this was its only link, it is no longer synced and rows can be entered by hand again.',
					verb: 'Unlink',
					busy: 'Unlinking…',
					destructive: true
				};
		}
	});
</script>

<ActionDialog
	open={flow.open}
	onclose={() => flow.close()}
	title={copy.title}
	description={copy.description}
	mode="decision"
	verb={copy.verb}
	busyVerb={copy.busy}
	destructive={copy.destructive}
	busy={flow.busy}
	onsubmit={() => void flow.confirm()}
	feedback={flow.error ? { kind: 'error', text: flow.error } : null}
>
	{#if flow.kind === 'delete'}
		<p>An importer that has run cannot be deleted: its runs stay as history. Disable it instead.</p>
	{:else if flow.kind === 'reset'}
		<p>Nothing is imported or removed.</p>
	{:else}
		<p>You can link it again later.</p>
	{/if}
</ActionDialog>
