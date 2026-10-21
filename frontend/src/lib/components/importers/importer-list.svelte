<script lang="ts">
	import Link2Icon from '@lucide/svelte/icons/link-2';
	import PencilIcon from '@lucide/svelte/icons/pencil';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import RowActions, { type RowAction } from '#lib/components/common/row-actions.svelte';
	import RefreshCwIcon from '@lucide/svelte/icons/refresh-cw';
	import { canRefreshAccounts } from '#lib/importers/discovery.js';
	import { canReset, hasRuns, importerTitle, lastRunText, loginText } from '#lib/importers/list.js';
	import { accountUrl, instanceUrl } from '#lib/importers/links.js';
	import type { CatalogEntry, ImporterInstance } from '#lib/types/domain.js';
	import type { Lookups } from '#lib/ledger/lookups.js';

	// The importer instances (ux/views/importers.md "The instance list"): the label (a link to its
	// page), its importer, the accounts it links to, when it last ran and "disabled" where it is. The
	// settings-row rule (patterns §11.3): "Edit" and "Link account" ("Refresh accounts" for an
	// importer that fetches) as icons, one `⋯` menu with
	// Disable or Enable, Reset… (an importer that keeps state) and, last, Delete…, which stays visible
	// but disabled, with its reason, on an instance that has run. An instance that holds a login says
	// whose ("your login", "<Name>’s login" or "shared"); the other user's login is read-only: its row
	// has no actions and opens its page.
	let {
		instances,
		catalog,
		status,
		lookups,
		locale = 'en',
		timeZone = 'UTC',
		busy = [],
		failure = null,
		onadd,
		onretry,
		onedit,
		onlink,
		onrefresh,
		ontoggle,
		onreset,
		ondelete
	}: {
		instances: readonly ImporterInstance[];
		catalog: readonly CatalogEntry[];
		status: 'loading' | 'ready' | 'error';
		lookups: Lookups;
		locale?: string;
		timeZone?: string;
		/** instances whose Disable or Enable is running */
		busy?: readonly number[];
		failure?: string | null;
		onadd?: () => void;
		onretry?: () => void;
		onedit?: (instance: ImporterInstance) => void;
		onlink?: (instance: ImporterInstance) => void;
		/** "Refresh accounts", for an instance of an importer that fetches */
		onrefresh?: (instance: ImporterInstance) => void;
		ontoggle?: (instance: ImporterInstance) => void;
		onreset?: (instance: ImporterInstance) => void;
		ondelete?: (instance: ImporterInstance) => void;
	} = $props();

	const importerName = (instance: ImporterInstance) => importerTitle(instance.importer);

	function primary(instance: ImporterInstance): RowAction[] {
		const edit: RowAction = {
			verb: 'Edit',
			label: `Edit ${instance.label}`,
			icon: PencilIcon,
			onselect: () => onedit?.(instance)
		};
		// an importer that fetches and emits transactions finds its accounts at the bank
		if (canRefreshAccounts(instance, catalog)) {
			return [
				edit,
				{
					verb: 'Refresh accounts',
					label: `Refresh the accounts of ${instance.label}`,
					icon: RefreshCwIcon,
					onselect: () => onrefresh?.(instance),
					disabled: instance.disabled
				}
			];
		}
		return [
			edit,
			{
				verb: 'Link account',
				label: `Link an account to ${instance.label}`,
				icon: Link2Icon,
				onselect: () => onlink?.(instance),
				disabled: instance.disabled || !instance.emits.includes('transactions')
			}
		];
	}

	function menu(instance: ImporterInstance): RowAction[] {
		const items: RowAction[] = [
			{
				verb: instance.disabled ? 'Enable' : 'Disable',
				onselect: () => ontoggle?.(instance),
				disabled: busy.includes(instance.id)
			}
		];
		if (canReset(instance, catalog)) {
			items.push({ verb: 'Reset…', onselect: () => onreset?.(instance) });
		}
		const ran = hasRuns(instance);
		items.push({
			verb: 'Delete…',
			destructive: true,
			onselect: () => ondelete?.(instance),
			disabled: ran,
			reason: ran ? 'has runs; disable it instead' : undefined
		});
		return items;
	}
</script>

{#if status === 'error'}
	<ErrorState
		title="The importers could not be loaded"
		message={failure ?? 'The server could not answer this request.'}
		{onretry}
	/>
{:else if status === 'loading'}
	<div class="flex flex-col gap-2" aria-busy="true" data-slot="importers-loading">
		{#each [0, 1, 2] as i (i)}
			<div class="h-12 animate-pulse rounded-lg bg-muted"></div>
		{/each}
	</div>
{:else if instances.length === 0}
	<EmptyState title="No importers yet" actionLabel="Add importer" onaction={onadd}>
		An importer reads a statement export or fetches from a bank. Add one, link it to an account, and
		upload a file from the account's page.
	</EmptyState>
{:else}
	<ul class="flex flex-col rounded-xl border bg-card shadow-card" data-slot="importer-list">
		{#each instances as instance (instance.id)}
			{@const run = lastRunText(instance.last_run_at, timeZone, locale)}
			{@const login = loginText(instance, catalog)}
			<li
				class="group grid min-h-12 grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-x-4 border-b border-border px-4 py-1.5 last:border-b-0"
				data-instance-id={instance.id}
			>
				<div class="flex min-w-0 flex-col">
					<span class="flex min-w-0 items-baseline gap-2">
						<a
							href={instanceUrl(instance.id)}
							class="truncate text-sm font-medium underline-offset-2 hover:underline"
						>
							{instance.label}
						</a>
						{#if instance.disabled}
							<span class="shrink-0 text-xs text-muted-foreground">disabled</span>
						{/if}
					</span>
					<span class="truncate text-xs text-muted-foreground">
						{importerName(instance)}
						·
						<span title={run.title}>{run.text}</span>
						{#if login}
							·
							<span data-slot="login">{login}</span>
						{/if}
					</span>
				</div>
				<div class="flex min-w-0 flex-wrap items-center gap-x-3 text-sm">
					{#each instance.accounts as link (link.account_id)}
						<a
							href={accountUrl(link.account_id)}
							class="truncate underline-offset-2 hover:underline"
						>
							{lookups.accounts.get(link.account_id)?.name ?? `Account #${link.account_id}`}
						</a>
					{:else}
						<span class="text-muted-foreground">no accounts linked</span>
					{/each}
				</div>
				{#if instance.manageable}
					<RowActions name={instance.label} primary={primary(instance)} menu={menu(instance)} />
				{/if}
			</li>
		{/each}
	</ul>
{/if}
