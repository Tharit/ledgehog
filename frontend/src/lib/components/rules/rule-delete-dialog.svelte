<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { formatCount } from '#lib/format/index.js';
	import type { RuleDeleteFlow } from '#lib/stores/rule-delete.svelte.js';

	// Deleting a rule asks first, with the numbers from the dry run: the entries it matches and the
	// entries that carry its key (patterns §6). The count is the server's, and the confirmation
	// carries it; if it moved, nothing is deleted and the new numbers are shown.
	let { flow, locale = 'en' }: { flow: RuleDeleteFlow; locale?: string } = $props();

	const count = (n: number) => formatCount(n, locale);
	const entries = (n: number) => `${count(n)} ${n === 1 ? 'entry' : 'entries'}`;
	const preview = $derived(flow.preview);
</script>

<Dialog.Root
	open={flow.open}
	onOpenChange={(next) => {
		if (!next && flow.status !== 'deleting') flow.close();
	}}
>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>Delete the rule “{flow.rule?.name ?? ''}”?</Dialog.Title>
			<Dialog.Description>
				No entry changes its value. Entries that were decided by this rule keep their values and
				show “rule deleted” as the reason.
			</Dialog.Description>
		</Dialog.Header>

		{#if flow.status === 'previewing'}
			<p class="text-sm text-muted-foreground" aria-busy="true">Checking what it touches…</p>
		{:else if preview}
			<ul class="flex flex-col gap-1 text-sm" data-slot="delete-preview">
				<li>
					Matches <span class="font-medium">{entries(preview.matches.total)}</span> now.
				</li>
				<li>
					<span class="font-medium">{entries(preview.lost_key.total)}</span>
					{preview.lost_key.total === 1 ? 'carries' : 'carry'} its key.
				</li>
			</ul>
		{/if}

		{#if flow.conflict}
			<p role="status" class="text-sm">{flow.conflict}</p>
		{/if}
		{#if flow.error}
			<p role="alert" class="text-sm text-destructive">{flow.error}</p>
		{/if}

		<Dialog.Footer>
			<Button variant="outline" disabled={flow.status === 'deleting'} onclick={() => flow.close()}>
				Cancel
			</Button>
			<Button variant="destructive" disabled={!flow.canConfirm} onclick={() => flow.confirm()}>
				{flow.status === 'deleting' ? 'Deleting…' : 'Delete'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
