<script lang="ts">
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import TagChip from '#lib/components/common/tag-chip.svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import Picker from '#lib/components/common/picker.svelte';
	import { formatCount, formatDate } from '#lib/format/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { tagItems } from '#lib/ledger/tag-items.js';
	import { extrasLabel, markedExplanation, rowsPhrase } from '#lib/ledger/tag-all.js';
	import type { TagAllFlow } from '#lib/stores/tag-all.svelte.js';
	import { resolveAccount, resolveTag } from '#lib/theme/resolve.js';
	import type { TagApplyOut } from '#lib/types/domain.js';

	// "Tag all…": a visible button for the filter bar and the decision dialog it opens (decisions
	// C6, C7; patterns §11.2). The dialog previews before it writes and its verb carries the number
	// ("Tag 214 entries"); the flow holds the state, this shows it.
	let {
		flow,
		lookups,
		locale = 'en',
		reason = null
	}: {
		flow: TagAllFlow;
		lookups: Lookups;
		locale?: string;
		/** why the action is not available now; null when it is */
		reason?: string | null;
	} = $props();

	const count = (n: number) => formatCount(n, locale);
	const busy = $derived(flow.status !== 'idle');
	const preview = $derived(flow.preview);
	const tags = $derived([...lookups.tags.values()]);
	// what "Tag" would do now: the entries the filter result gains plus the opted-in rows
	const total = $derived((preview?.newly_tagged ?? 0) + flow.extraCount);
	const verb = $derived(
		total > 0 ? `Tag ${count(total)} ${total === 1 ? 'entry' : 'entries'}` : 'Tag'
	);
	const title = $derived(
		preview
			? `Tag all ${count(preview.selected)} ${preview.selected === 1 ? 'entry' : 'entries'}`
			: 'Tag all matching entries'
	);
	const feedback = $derived.by<DialogFeedback | null>(() => {
		if (flow.report.length > 0) {
			return { kind: 'report', text: flow.report[0], lines: flow.report.slice(1) };
		}
		if (flow.conflict) return { kind: 'conflict', text: flow.conflict };
		if (flow.error) {
			const retry = flow.tag && !preview && flow.status === 'idle';
			return {
				kind: 'error',
				text: flow.error,
				action: retry ? { label: 'Try again', onclick: () => void flow.retry() } : undefined
			};
		}
		return null;
	});

	function span(span: TagApplyOut['span_before']): string {
		return span.starts_on && span.ends_on
			? `${formatDate(span.starts_on, locale)} – ${formatDate(span.ends_on, locale)}`
			: 'no entries yet';
	}
</script>

<span class="ml-auto inline-flex">
	<ActionButton
		variant="outline"
		disabled={reason !== null}
		reason={reason ?? undefined}
		onclick={() => flow.start()}
	>
		Tag all…
	</ActionButton>
</span>

<!-- the number in the title is the server's, for what the filter matches now; the list may be a snapshot -->
<ActionDialog
	open={flow.open}
	onclose={() => flow.close()}
	{title}
	description="Adds a tag to every entry the current filter matches, on every page. Tags already on them stay."
	mode="decision"
	{verb}
	busyVerb="Tagging…"
	busy={flow.status === 'applying'}
	disabled={!flow.canConfirm}
	onsubmit={() => void flow.confirm()}
	{feedback}
>
	{#if flow.marked.length > 0}
		<p class="text-sm text-muted-foreground" data-slot="marked-explanation">
			{markedExplanation(flow.marked.length, locale)}
		</p>
	{/if}

	{#if flow.tag === null}
		<Picker
			items={tagItems(tags)}
			{busy}
			label="Tags"
			findLabel="Search tags"
			placeholder="Find or add a tag…"
			emptyText="No tags yet. Type a name to add one."
			createLabel={(name) => `Add tag “${name}”`}
			onselect={(id) => {
				const tag = tags.find((t) => t.id === id);
				if (tag) void flow.choose(tag);
			}}
			oncreate={(name) => void flow.create(name)}
		/>
	{:else}
		<div class="flex items-center justify-between gap-2">
			<span class="flex items-center gap-2">
				<span class="text-muted-foreground">Tag</span>
				<TagChip name={flow.tag.name} color={resolveTag(flow.tag).color} />
			</span>
			<ActionButton variant="ghost" disabled={busy} onclick={() => flow.back()}>
				Change tag
			</ActionButton>
		</div>

		{#if flow.status === 'previewing'}
			<p class="text-sm text-muted-foreground" aria-busy="true">Checking what would change…</p>
		{:else if preview}
			<div class="flex flex-col gap-1.5 text-sm" data-slot="tag-preview">
				{#if preview.newly_tagged > 0}
					<p class="font-medium">
						{count(preview.newly_tagged)}
						{preview.newly_tagged === 1 ? 'entry' : 'entries'} will be tagged
					</p>
				{:else if flow.extraCount === 0}
					<p class="font-medium">Nothing to tag</p>
				{/if}
				{#if flow.extraCount > 0}
					<p class="font-medium">
						{preview.newly_tagged > 0 ? 'plus ' : ''}{rowsPhrase(flow.extraCount, locale)} you changed
					</p>
				{/if}
				<p class="text-muted-foreground">
					{count(preview.already_tagged)} already carry{preview.already_tagged === 1 ? 'es' : ''} it
				</p>
				{#if preview.skipped_derived > 0}
					<p class="text-muted-foreground">
						{count(preview.skipped_derived)} derived
						{preview.skipped_derived === 1 ? 'entry' : 'entries'} skipped
					</p>
				{/if}
				<p class="text-muted-foreground">
					Span of the tag: {span(preview.span_before)} → {span(preview.span_after)}
				</p>
				{#if flow.extraRows.length > 0}
					<label class="mt-1 flex items-center gap-2">
						<input type="checkbox" bind:checked={flow.includeMarked} disabled={busy} />
						<span>{extrasLabel(flow.extraRows.length, locale)}</span>
					</label>
				{/if}
				{#if preview.per_account.length > 0}
					<ul class="mt-1 flex flex-col gap-0.5" aria-label="Newly tagged by account">
						{#each preview.per_account as row (row.account_id)}
							{@const account = lookups.accounts.get(row.account_id)}
							<li class="flex items-center justify-between gap-2">
								<AccountDot
									name={account ? account.name : `Account ${row.account_id}`}
									color={account ? resolveAccount(account).color : null}
								/>
								<span class="tabular-nums">{count(row.newly_tagged)}</span>
							</li>
						{/each}
					</ul>
				{/if}
			</div>
		{/if}
	{/if}
</ActionDialog>
