<script lang="ts">
	import Card from '#lib/components/common/card.svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import { formatDate } from '#lib/format/index.js';
	import type { AccountInfo } from '#lib/sync/progress.js';
	import type { PlanInstance } from '#lib/types/domain.js';
	import PlanAccountRow from './plan-account-row.svelte';

	// The page with nothing running (ux/views/sync.md "Starting"): what "sync everything" would do. One
	// block per login with its accounts below; a login another sync holds says so and is left out.
	// "Start sync" syncs every login the plan shows, there is no selection; a refused start stands above
	// the button. With nothing to fetch the page says so and links to Settings → Importers.
	let {
		plan,
		status = 'ready',
		narrowed = false,
		accountOf = () => null,
		starts = $bindable({}),
		refusal = null,
		starting = false,
		locale = 'en',
		onstart,
		onretry
	}: {
		/** the logins to show, narrowed by the address where it names one */
		plan: readonly PlanInstance[];
		status?: 'loading' | 'ready' | 'error';
		/** the plan is narrowed to one login or account by the address */
		narrowed?: boolean;
		accountOf?: (accountId: number) => AccountInfo | null;
		/** the starts the user chose, by account id */
		starts?: Record<number, string>;
		refusal?: string | null;
		starting?: boolean;
		locale?: string;
		onstart?: () => void;
		onretry?: () => void;
	} = $props();

	const runnable = $derived(plan.filter((i) => !i.busy).length);
</script>

{#if status === 'loading'}
	<p class="text-sm text-muted-foreground" aria-busy="true">Reading what there is to fetch…</p>
{:else if status === 'error'}
	<ErrorState
		title="The plan could not be loaded"
		message="The server could not answer this request. Try again in a moment."
		{onretry}
		class="max-w-none items-center p-8 text-center"
	/>
{:else if plan.length === 0}
	{#if narrowed}
		<EmptyState title="Nothing to fetch here" actionLabel="Show the whole plan" actionHref="/sync">
			That login or account is not part of what can be fetched now.
		</EmptyState>
	{:else}
		<EmptyState
			title="Nothing to fetch yet"
			actionLabel="Open Importers"
			actionHref="/settings/importers"
		>
			Link an account to a login in Settings → Importers, and it can be fetched here.
		</EmptyState>
	{/if}
{:else}
	<div class="flex flex-col gap-4" data-slot="sync-plan">
		{#each plan as instance (instance.instance_id)}
			<Card
				element="section"
				class="flex flex-col gap-1"
				data-slot="plan-instance"
				data-busy={instance.busy}
				aria-label={instance.label}
			>
				<div class="flex flex-wrap items-baseline justify-between gap-x-3">
					<h2 class="text-sm font-semibold">
						{instance.label}
						<span class="font-normal text-muted-foreground">· {instance.importer}</span>
					</h2>
					{#if instance.busy}
						<span class="text-sm text-muted-foreground" data-slot="plan-busy">
							another sync is using this login
						</span>
					{/if}
				</div>
				<ul class="flex flex-col">
					{#each instance.accounts as account (account.account_id)}
						<PlanAccountRow
							{account}
							info={accountOf(account.account_id)}
							start={starts[account.account_id] ?? ''}
							onchange={(value) => (starts = { ...starts, [account.account_id]: value })}
							disabled={instance.busy || starting}
							{locale}
						/>
					{/each}
					{#if instance.documents_since !== null}
						<li
							class="flex flex-wrap items-center gap-x-4 gap-y-1 py-1.5 text-[13px]"
							data-slot="plan-documents"
						>
							<span class="min-w-40 font-medium">Documents</span>
							<span class="text-muted-foreground">
								from {formatDate(instance.documents_since, locale)}
							</span>
						</li>
					{/if}
				</ul>
			</Card>
		{/each}

		<div class="flex flex-col items-end gap-2">
			{#if refusal}
				<Notice role="alert">{refusal}</Notice>
			{/if}
			<ActionButton
				busy={starting}
				busyLabel="Starting…"
				disabled={runnable === 0}
				reason={runnable === 0 ? 'Every login is in use by another sync.' : undefined}
				onclick={onstart}
			>
				Start sync
			</ActionButton>
		</div>
	</div>
{/if}
