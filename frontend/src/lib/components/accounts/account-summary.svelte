<script lang="ts">
	import EllipsisIcon from '@lucide/svelte/icons/ellipsis';
	import { uploadHref, type SourceLine } from '#lib/accounts/sources.js';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import IconButton from '#lib/components/common/icon-button.svelte';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.js';
	import type { Account } from '#lib/types/domain.js';
	import AccountFacts from './account-facts.svelte';

	// What stands under the account page's header (ux/views/account.md): the balance and its facts
	// line, the sources (each linked importer instance with its action, or how an unlinked account is
	// fed), "Set balance" and "View entries", and the `⋯` menu with Edit, Close… or Reopen, and Delete…
	// last and destructive. A fetch importer's line has "Fetch", where a file importer's has "Upload
	// file".
	let {
		account,
		sources,
		sourcesStatus = 'ready',
		locale = 'en',
		today,
		onsetbalance,
		onedit,
		onclose,
		onreopen,
		ondelete,
		onfetch
	}: {
		account: Account;
		sources: readonly SourceLine[];
		/** the instances are still being read, or could not be */
		sourcesStatus?: 'loading' | 'ready' | 'error';
		locale?: string;
		today: string;
		onsetbalance: () => void;
		onedit: () => void;
		onclose: () => void;
		onreopen: () => void;
		ondelete: () => void;
		/** "Fetch" on the line of a fetch importer: a one-item sync of this account (ux/views/sync.md) */
		onfetch?: (instanceId: number) => void;
	} = $props();

	const closed = $derived(account.closed_on !== null);
</script>

<section class="flex flex-col gap-3" aria-label="Account summary" data-slot="account-summary">
	<div class="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
		<AccountFacts {account} {locale} {today} />
		<div class="flex items-center gap-2">
			<ActionButton variant="outline" onclick={onsetbalance}>Set balance</ActionButton>
			<ActionButton variant="outline" href={`/ledger?account_id=${account.id}`}>
				View entries
			</ActionButton>
			<DropdownMenu.Root>
				<DropdownMenu.Trigger>
					{#snippet child({ props })}
						<IconButton
							tooltip={false}
							verb="More actions"
							name={account.name}
							label={`More actions for ${account.name}`}
							{...props}
						>
							<EllipsisIcon aria-hidden="true" />
						</IconButton>
					{/snippet}
				</DropdownMenu.Trigger>
				<DropdownMenu.Content align="end" class="min-w-44">
					<DropdownMenu.Item onSelect={onedit}>Edit</DropdownMenu.Item>
					{#if closed}
						<DropdownMenu.Item onSelect={onreopen}>Reopen</DropdownMenu.Item>
					{:else}
						<DropdownMenu.Item onSelect={onclose}>Close…</DropdownMenu.Item>
					{/if}
					<DropdownMenu.Separator />
					<DropdownMenu.Item variant="destructive" onSelect={ondelete}>Delete…</DropdownMenu.Item>
				</DropdownMenu.Content>
			</DropdownMenu.Root>
		</div>
	</div>

	<div class="flex flex-col gap-1 text-sm" data-slot="sources">
		<h2 class="text-xs font-medium text-muted-foreground">Sources</h2>
		{#if sourcesStatus === 'loading'}
			<p class="text-muted-foreground">Looking up the importers…</p>
		{:else if sourcesStatus === 'error'}
			<p class="text-muted-foreground">The importers could not be loaded.</p>
		{:else if sources.length === 0}
			<p class="text-muted-foreground" data-slot="unlinked">
				Entered by hand. To feed it from a file or a sync, link it to an importer in
				<a href="/settings/importers" class="text-foreground underline underline-offset-2"
					>Settings → Importers</a
				>.
			</p>
		{:else}
			<ul class="flex flex-col gap-1">
				{#each sources as source (source.instanceId)}
					<li
						class="flex flex-wrap items-center gap-x-3 gap-y-1"
						data-source-instance={source.instanceId}
					>
						<span class="font-medium">{source.label}</span>
						<span class="text-muted-foreground">
							{source.importer}{source.disabled ? ' · disabled' : ''}
						</span>
						{#if source.kind === 'file'}
							<ActionButton
								variant="outline"
								href={uploadHref(account.id, source.instanceId)}
								disabled={source.disabled}
							>
								Upload file
							</ActionButton>
						{:else}
							<ActionButton
								variant="outline"
								disabled={source.disabled}
								onclick={() => onfetch?.(source.instanceId)}
							>
								Fetch
							</ActionButton>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</div>
</section>
