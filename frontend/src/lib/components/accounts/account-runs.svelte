<script lang="ts">
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import { LATEST_RUNS, statusLabel, summaryLine, type ImportRun } from '#lib/accounts/runs.js';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import RunSummary from '#lib/components/importers/run-summary.svelte';
	import { formatDate, formatInstant } from '#lib/format/index.js';
	import { cn } from '#lib/utils.js';

	// The account's import log (ux/views/account.md "Runs"): the latest five runs, "Show all" for the
	// rest. A row shows the instance, the start as an instant, its status, "covered through" and one
	// line of its summary, and opens the run summary in place. A reverted run is marked; a failed one
	// shows its error. "Revert…" is offered on the one run the server marks revertible; an earlier
	// successful run says that later runs are reverted first.
	let {
		runs,
		status,
		instanceLabel,
		showAll = false,
		currency,
		locale = 'en',
		timeZone = 'UTC',
		onshowall,
		onrevert,
		onretry
	}: {
		runs: readonly ImportRun[];
		status: 'loading' | 'ready' | 'error';
		/** the label of the instance a run came from; a deleted instance has none */
		instanceLabel: (run: ImportRun) => string;
		showAll?: boolean;
		currency: string;
		locale?: string;
		timeZone?: string;
		onshowall?: () => void;
		onrevert?: (run: ImportRun) => void;
		onretry?: () => void;
	} = $props();

	let openId = $state<number | null>(null);
	const shown = $derived(showAll ? runs : runs.slice(0, LATEST_RUNS));
</script>

<section class="flex flex-col gap-1" aria-label="Runs" data-slot="account-runs">
	<h2 class="text-xs font-medium text-muted-foreground">Runs</h2>
	{#if status === 'loading'}
		<p class="text-sm text-muted-foreground">Loading the runs…</p>
	{:else if status === 'error'}
		<Notice role="alert">
			The runs could not be loaded.
			{#snippet action()}
				<ActionButton variant="link" class="h-auto p-0" onclick={onretry}>Try again</ActionButton>
			{/snippet}
		</Notice>
	{:else if runs.length === 0}
		<p class="text-sm text-muted-foreground" data-slot="no-runs">
			No import has run for this account.
		</p>
	{:else}
		<ul class="flex flex-col">
			{#each shown as run (run.id)}
				{@const open = openId === run.id}
				<li class="border-b border-border" data-run-id={run.id} data-status={run.status}>
					<div class="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-[13px]">
						<button
							type="button"
							class="flex min-w-0 flex-1 items-center gap-2 rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
							aria-expanded={open}
							aria-label={`Run of ${instanceLabel(run)}, ${formatInstant(run.started_at, timeZone, locale)}`}
							onclick={() => (openId = open ? null : run.id)}
						>
							<ChevronRightIcon
								size={14}
								strokeWidth={1.75}
								class={cn(
									'shrink-0 text-muted-foreground transition-transform',
									open && 'rotate-90'
								)}
								aria-hidden="true"
							/>
							<span class="font-medium">{instanceLabel(run)}</span>
							<time class="text-muted-foreground" datetime={run.started_at}>
								{formatInstant(run.started_at, timeZone, locale)}
							</time>
							<span
								data-slot="run-status"
								class={run.status === 'reverted' ? 'text-muted-foreground' : ''}
							>
								{statusLabel(run.status)}
							</span>
							{#if run.covered_through}
								<span class="text-muted-foreground">
									covered through {formatDate(run.covered_through, locale)}
								</span>
							{/if}
							{#if run.status === 'failed'}
								<span class="min-w-0 truncate text-muted-foreground" data-slot="run-error-line">
									{run.error_text ?? 'No error was recorded.'}
								</span>
							{:else}
								<span class="min-w-0 truncate text-muted-foreground" data-slot="run-line">
									{summaryLine(run)}
								</span>
							{/if}
						</button>
						{#if run.revertible}
							<ActionButton variant="outline" onclick={() => onrevert?.(run)}>Revert…</ActionButton>
						{:else if run.status === 'ok'}
							<span class="text-xs text-muted-foreground" data-slot="later-first">
								Later runs are reverted first.
							</span>
						{/if}
					</div>
					{#if open}
						<div class="pb-3 pl-6">
							<RunSummary {run} {currency} {locale} />
						</div>
					{/if}
				</li>
			{/each}
		</ul>
		{#if !showAll && runs.length > LATEST_RUNS}
			<div>
				<ActionButton variant="link" class="h-auto p-0" onclick={onshowall}>Show all</ActionButton>
			</div>
		{/if}
	{/if}
</section>
