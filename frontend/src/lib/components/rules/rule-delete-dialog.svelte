<script lang="ts">
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import { formatCount } from '#lib/format/index.js';
	import type { RuleDeleteFlow } from '#lib/stores/rule-delete.svelte.js';

	// Deleting a rule is a decision dialog (patterns §11.2): it asks first, with the numbers from
	// the dry run: the entries it matches and the entries that carry its key (patterns §6). The
	// count is the server's, and the confirmation carries it; if it moved, nothing is deleted and
	// the new numbers are shown.
	let { flow, locale = 'en' }: { flow: RuleDeleteFlow; locale?: string } = $props();

	const count = (n: number) => formatCount(n, locale);
	const entries = (n: number) => `${count(n)} ${n === 1 ? 'entry' : 'entries'}`;
	const preview = $derived(flow.preview);
	const feedback = $derived<DialogFeedback | null>(
		flow.error
			? { kind: 'error', text: flow.error }
			: flow.conflict
				? { kind: 'conflict', text: flow.conflict }
				: null
	);
</script>

<ActionDialog
	open={flow.open}
	onclose={() => flow.close()}
	title={`Delete the rule “${flow.rule?.name ?? ''}”?`}
	description="No entry changes its value. Entries that were decided by this rule keep their values and show “rule deleted” as the reason."
	mode="decision"
	verb="Delete"
	busyVerb="Deleting…"
	destructive
	busy={flow.status === 'deleting'}
	disabled={!flow.canConfirm}
	onsubmit={() => void flow.confirm()}
	{feedback}
>
	{#if flow.status === 'previewing'}
		<p class="text-muted-foreground" aria-busy="true">Checking what it touches…</p>
	{:else if preview}
		<ul class="flex flex-col gap-1" data-slot="delete-preview">
			<li>
				Matches <span class="font-medium">{entries(preview.matches.total)}</span> now.
			</li>
			<li>
				<span class="font-medium">{entries(preview.lost_key.total)}</span>
				{preview.lost_key.total === 1 ? 'carries' : 'carry'} its key.
			</li>
		</ul>
	{/if}
</ActionDialog>
