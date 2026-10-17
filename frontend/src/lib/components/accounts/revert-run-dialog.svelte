<script lang="ts">
	import { untrack } from 'svelte';
	import { RevertFlow } from '#lib/accounts/revert-flow.svelte.js';
	import type { ImportRun } from '#lib/accounts/runs.js';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import { formatCount, formatInstant } from '#lib/format/index.js';

	// "Revert…" a run (spec §5.6, ux/views/account.md): a decision dialog whose body is the revert's
	// preview as a consequence list (patterns §6): the rows the run brought, the entries removed,
	// confirmed ones by count, and the partners unpaired and returned to review. The verb is "Revert
	// run".
	let {
		open,
		run,
		label,
		locale = 'en',
		timeZone = 'UTC',
		flow = new RevertFlow(),
		onclose,
		onreverted
	}: {
		open: boolean;
		run: ImportRun | null;
		/** what the run is called: its instance's label */
		label: string;
		locale?: string;
		timeZone?: string;
		flow?: RevertFlow;
		onclose: () => void;
		onreverted: () => void;
	} = $props();

	$effect(() => {
		if (!open || !run) {
			untrack(() => flow.stop());
			return;
		}
		const shown = run;
		untrack(() => flow.start(shown));
		return () => flow.stop();
	});

	async function confirm() {
		if (await flow.confirm()) onreverted();
	}

	const feedback = $derived<DialogFeedback | null>(
		flow.failure
			? {
					kind: flow.failure.kind,
					text: flow.failure.text,
					action:
						flow.status === 'error' && flow.failure.retryable
							? { label: 'Try again', onclick: () => void flow.check() }
							: undefined
				}
			: null
	);

	const n = (count: number, one: string, many: string) =>
		`${formatCount(count, locale)} ${count === 1 ? one : many}`;
	const brought = $derived(run?.stats.inserted ?? 0);
</script>

<ActionDialog
	{open}
	{onclose}
	mode="decision"
	destructive
	title="Revert run"
	description={run ? `${label}, ${formatInstant(run.started_at, timeZone, locale)}` : undefined}
	verb="Revert run"
	busyVerb="Reverting…"
	busy={flow.busy}
	disabled={!flow.canRevert}
	onsubmit={confirm}
	{feedback}
>
	{#if flow.status === 'checking'}
		<p class="text-muted-foreground" data-slot="revert-checking">Checking what would change…</p>
	{:else if flow.status === 'ready' && flow.preview}
		{@const out = flow.preview}
		<ul class="flex list-disc flex-col gap-1 pl-5" data-slot="revert-consequences">
			<li>
				The rows this run brought ({n(brought, 'row', 'rows')}) are deleted, with
				{n(out.removed_entry_ids.length, 'entry', 'entries')}, of which
				{formatCount(out.removed_confirmed, locale)} confirmed.
			</li>
			{#if out.partner_entry_ids.length > 0}
				<li>
					{n(out.partner_entry_ids.length, 'partner entry', 'partner entries')} are unpaired and return
					to review, of which {formatCount(out.partner_confirmed, locale)} confirmed.
				</li>
			{/if}
			{#if out.cleared_duplicate_ids.length > 0}
				<li>
					{n(out.cleared_duplicate_ids.length, 'row', 'rows')} stop being duplicates and get an entry.
				</li>
			{/if}
			{#if out.repointed_source_ids.length > 0}
				<li>
					{n(out.repointed_source_ids.length, 'duplicate', 'duplicates')} point to another original.
				</li>
			{/if}
			{#if out.freed_document_ids.length > 0}
				<li>{n(out.freed_document_ids.length, 'document', 'documents')} are freed.</li>
			{/if}
		</ul>
	{/if}
</ActionDialog>
