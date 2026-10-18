<script lang="ts">
	import ActionButton from '#lib/components/common/action-button.svelte';
	import { ACCOUNT_KINDS } from '#lib/accounts/kinds.js';
	import { NOTHING_TO_FETCH_TEXT, rowState, type RowState } from '#lib/importers/discovery.js';
	import { accountUrl } from '#lib/importers/links.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import type { DiscoveryEntry } from '#lib/types/domain.js';

	// One row per account the login reaches (ux/views/importers.md "Refresh accounts"): its name, its
	// currency, its kind and the reference as the bank reports it, and what it is here: linked,
	// nothing to fetch, a closed account's (not offered), a match with "Link…", or "Add and link". A row
	// changes state in place when the result is read again; the order never changes.
	let {
		entries,
		lookups,
		busyRefs = [],
		onlink,
		onadd
	}: {
		entries: readonly DiscoveryEntry[];
		lookups: Lookups;
		/** references whose add-and-link is under way */
		busyRefs?: readonly string[];
		onlink: (entry: DiscoveryEntry, state: Extract<RowState, { kind: 'match' }>) => void;
		onadd: (entry: DiscoveryEntry) => void;
	} = $props();

	const nameOf = (id: number) => lookups.accounts.get(id)?.name ?? `Account #${id}`;
	const kindText = (hint: string | null) =>
		hint === null ? null : (ACCOUNT_KINDS.find((k) => k.kind === hint)?.label ?? hint);
</script>

<ul class="flex flex-col rounded-xl border bg-card shadow-card" data-slot="discovery-rows">
	{#each entries as entry (entry.account.external_ref)}
		{@const state = rowState(entry)}
		{@const ref = entry.account.external_ref}
		<li
			class="grid min-h-14 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 border-b border-border px-4 py-2 last:border-b-0"
			data-state={state.kind}
		>
			<div class="flex min-w-0 flex-col" class:text-muted-foreground={state.kind === 'closed'}>
				<span class="truncate text-sm font-medium">{entry.account.name}</span>
				<span class="truncate text-xs text-muted-foreground">
					{#each [entry.account.currency, kindText(entry.account.kind_hint)].filter(Boolean) as fact (fact)}
						{fact} ·
					{/each}
					<span class="font-mono">{ref}</span>
				</span>
			</div>
			<div class="flex items-center justify-end gap-2 text-sm">
				{#if state.kind === 'linked'}
					<span>
						Linked to
						<a href={accountUrl(state.accountId)} class="underline underline-offset-2">
							{nameOf(state.accountId)}
						</a>
					</span>
				{:else if state.kind === 'nothing_to_fetch'}
					<span class="max-w-72 text-right text-muted-foreground">{NOTHING_TO_FETCH_TEXT}</span>
				{:else if state.kind === 'closed'}
					<span class="text-muted-foreground"
						>Matches a closed account, {nameOf(state.accountId)}</span
					>
				{:else if state.kind === 'match'}
					<ActionButton
						variant="outline"
						aria-label={`Link ${entry.account.name}`}
						onclick={() => onlink(entry, state)}
					>
						Link…
					</ActionButton>
				{:else}
					<ActionButton
						variant="outline"
						aria-label={`Add and link ${entry.account.name}`}
						busy={busyRefs.includes(ref)}
						busyLabel="Linking…"
						onclick={() => onadd(entry)}
					>
						Add and link
					</ActionButton>
				{/if}
			</div>
		</li>
	{/each}
</ul>
