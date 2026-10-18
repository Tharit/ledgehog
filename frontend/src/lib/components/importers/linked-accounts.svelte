<script lang="ts">
	import ActionButton from '#lib/components/common/action-button.svelte';
	import { accountUrl } from '#lib/importers/links.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import type { ImporterInstance } from '#lib/types/domain.js';

	// The accounts an instance is linked to (ux/views/importers.md "The instance page"): each with
	// "Unlink…", and the action "Link account". Shown for an instance already saved.
	let {
		instance,
		lookups,
		refreshable = false,
		onlink,
		onrefresh,
		onunlink
	}: {
		instance: ImporterInstance;
		lookups: Lookups;
		/** the importer fetches and emits transactions: its accounts are found at the bank */
		refreshable?: boolean;
		onlink: () => void;
		onrefresh?: () => void;
		onunlink: (accountId: number) => void;
	} = $props();
</script>

<section
	class="flex flex-col gap-3 rounded-xl border bg-card p-5 shadow-card"
	aria-label="Linked accounts"
	data-slot="linked-accounts"
>
	<div class="flex flex-wrap items-center justify-between gap-2">
		<div class="flex flex-col gap-1">
			<h3 class="text-base font-semibold">Linked accounts</h3>
			<p class="max-w-prose text-sm text-muted-foreground">
				{refreshable
					? 'The accounts of this login that are fetched into the ledger.'
					: 'A file of this format is uploaded to one of these accounts, from the account’s page.'}
			</p>
		</div>
		<ActionButton
			variant="outline"
			disabled={instance.disabled}
			reason={instance.disabled ? 'Enable the importer first.' : undefined}
			onclick={refreshable ? onrefresh : onlink}
		>
			{refreshable ? 'Refresh accounts' : 'Link account'}
		</ActionButton>
	</div>
	{#if instance.accounts.length === 0}
		<p class="text-sm text-muted-foreground">No account is linked yet.</p>
	{:else}
		<ul class="flex flex-col">
			{#each instance.accounts as link (link.account_id)}
				{@const name = lookups.accounts.get(link.account_id)?.name ?? `Account #${link.account_id}`}
				<li
					class="flex min-h-10 items-center justify-between gap-3 border-b border-border py-1 last:border-b-0"
				>
					<a
						href={accountUrl(link.account_id)}
						class="truncate text-sm underline-offset-2 hover:underline"
					>
						{name}
					</a>
					<ActionButton
						variant="ghost"
						aria-label={`Unlink ${name}`}
						onclick={() => onunlink(link.account_id)}
					>
						Unlink…
					</ActionButton>
				</li>
			{/each}
		</ul>
	{/if}
</section>
