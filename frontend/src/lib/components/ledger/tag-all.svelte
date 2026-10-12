<script lang="ts">
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import TagChip from '#lib/components/common/tag-chip.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { formatCount, formatDate } from '#lib/format/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { extrasLabel, markedExplanation, rowsPhrase } from '#lib/ledger/tag-all.js';
	import type { TagAllFlow } from '#lib/stores/tag-all.svelte.js';
	import { resolveAccount, resolveTag } from '#lib/theme/resolve.js';
	import type { TagApplyOut } from '#lib/types/domain.js';
	import TagChooser from './tag-chooser.svelte';

	// "Tag all…": a visible button for the filter bar and the dialog it opens (decisions C6, C7).
	// The dialog previews before it writes; the flow holds the state, this shows it.
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

	function span(span: TagApplyOut['span_before']): string {
		return span.starts_on && span.ends_on
			? `${formatDate(span.starts_on, locale)} – ${formatDate(span.ends_on, locale)}`
			: 'no entries yet';
	}
</script>

<span class="ml-auto inline-flex" title={reason ?? undefined}>
	<Button variant="outline" size="sm" disabled={reason !== null} onclick={() => flow.start()}>
		Tag all…
	</Button>
</span>

<Dialog.Root
	open={flow.open}
	onOpenChange={(next) => {
		if (!next && flow.status !== 'applying') flow.close();
	}}
>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<!-- the number is the server's, for what the filter matches now; the list may be a snapshot -->
			<Dialog.Title>
				{#if preview}
					Tag all {count(preview.selected)} {preview.selected === 1 ? 'entry' : 'entries'}
				{:else}
					Tag all matching entries
				{/if}
			</Dialog.Title>
			<Dialog.Description>
				Adds a tag to every entry the current filter matches, on every page. Tags already on them
				stay.
			</Dialog.Description>
		</Dialog.Header>

		{#if flow.marked.length > 0}
			<p class="text-sm text-muted-foreground" data-slot="marked-explanation">
				{markedExplanation(flow.marked.length, locale)}
			</p>
		{/if}

		{#if flow.tag === null}
			<TagChooser
				tags={[...lookups.tags.values()]}
				{busy}
				onselect={(tag) => flow.choose(tag)}
				oncreate={(name) => flow.create(name)}
			/>
		{:else}
			<div class="flex items-center justify-between gap-2">
				<span class="flex items-center gap-2">
					<span class="text-muted-foreground">Tag</span>
					<TagChip name={flow.tag.name} color={resolveTag(flow.tag).color} />
				</span>
				<Button variant="ghost" size="xs" disabled={busy} onclick={() => flow.back()}>
					Change tag
				</Button>
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
						<label class="mt-1 flex cursor-pointer items-center gap-2">
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

		{#if flow.report.length > 0}
			<div role="alert" class="flex flex-col gap-1 text-sm" data-slot="tag-report">
				{#each flow.report as line, i (i)}
					<p>{line}</p>
				{/each}
			</div>
		{/if}
		{#if flow.conflict}
			<p role="status" class="text-sm">{flow.conflict}</p>
		{/if}
		{#if flow.error}
			<p role="alert" class="text-sm text-destructive">
				{flow.error}
				{#if flow.tag && !preview && flow.status === 'idle'}
					<button type="button" class="underline underline-offset-2" onclick={() => flow.retry()}>
						Try again
					</button>
				{/if}
			</p>
		{/if}

		<Dialog.Footer>
			<Button variant="outline" disabled={flow.status === 'applying'} onclick={() => flow.close()}>
				Cancel
			</Button>
			<Button disabled={!flow.canConfirm} onclick={() => flow.confirm()}>
				{flow.status === 'applying' ? 'Tagging…' : 'Confirm'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
