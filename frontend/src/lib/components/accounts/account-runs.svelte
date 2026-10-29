<script lang="ts">
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import { statusLabel, summaryLine, type ImportRun } from '#lib/accounts/runs.js';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import Card from '#lib/components/common/card.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import RunNextStep from '#lib/components/importers/run-next-step.svelte';
	import RunSummary from '#lib/components/importers/run-summary.svelte';
	import { formatCount, formatDate, formatInstant } from '#lib/format/index.js';
	import { cn } from '#lib/utils.js';

	// The account's import log (ux/views/account.md "Runs"): every run, newest first, paged like the statement ("n of total", "Load more").
	// A row shows the instance, the start as an instant, its status, "covered through" and one line of its summary, and opens the run summary in place. A reverted run is marked; a failed one
	// shows its error, then what to do next (`run-next-step`). "Revert…" is offered on the one run the server marks revertible; an earlier
	// successful run says that later runs are reverted first.
	let {
		runs,
		total,
		status,
		loadingMore = false,
		moreFailed = false,
		instanceLabel,
		importerKind = () => null,
		currency,
		locale = 'en',
		timeZone = 'UTC',
		onrevert,
		onretry,
		onrunagain,
		onloadmore
	}: {
		runs: readonly ImportRun[];
		/** every run the account has, whatever the page */
		total?: number;
		status: 'loading' | 'ready' | 'error';
		/** the label of the instance a run came from; a deleted instance has none */
		instanceLabel: (run: ImportRun) => string;
		/** what the importer a run came from is (the catalog says): it decides the next step of a failed run */
		importerKind?: (run: ImportRun) => 'file' | 'fetch' | null;
		currency: string;
		locale?: string;
		timeZone?: string;
		onrevert?: (run: ImportRun) => void;
		onretry?: () => void;
		/** "Run again" on a failed fetch run: a one-item sync of its instance and account */
		onrunagain?: (run: ImportRun) => void;
		onloadmore?: () => void | Promise<void>;
		loadingMore?: boolean;
		moreFailed?: boolean;
	} = $props();

	let openId = $state<number | null>(null);
	const count = $derived(total ?? runs.length);
</script>

<section class="flex flex-col gap-1" aria-label="Runs" data-slot="account-runs">
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
		<Card variant="flush" element="ul">
			{#each runs as run (run.id)}
				{@const open = openId === run.id}
				<li
					class="border-b border-border last:border-b-0"
					data-run-id={run.id}
					data-status={run.status}
				>
					<div class="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-1.5 text-[13px]">
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
						{#if run.status === 'failed'}
							<RunNextStep
								{run}
								importerKind={importerKind(run)}
								onrunagain={() => onrunagain?.(run)}
							/>
						{:else if run.revertible}
							<ActionButton variant="outline" onclick={() => onrevert?.(run)}>Revert…</ActionButton>
						{:else if run.status === 'ok'}
							<span class="text-xs text-muted-foreground" data-slot="later-first">
								Later runs are reverted first.
							</span>
						{/if}
					</div>
					{#if open}
						<div class="pr-4 pb-3 pl-10">
							<RunSummary {run} {currency} {locale} />
						</div>
					{/if}
				</li>
			{/each}
		</Card>
		<div
			class="flex flex-wrap items-center gap-3 py-3 text-xs text-muted-foreground"
			data-slot="runs-footer"
		>
			<span>{formatCount(runs.length, locale)} of {formatCount(count, locale)}</span>
			{#if runs.length < count}
				<ActionButton
					variant="outline"
					onclick={onloadmore}
					busy={loadingMore}
					busyLabel="Loading…"
				>
					Load more
				</ActionButton>
			{/if}
			{#if moreFailed}
				<Notice role="alert">
					More runs could not be loaded.
					{#snippet action()}
						<ActionButton variant="link" class="h-auto p-0" onclick={onloadmore}>
							Try again
						</ActionButton>
					{/snippet}
				</Notice>
			{/if}
		</div>
	{/if}
</section>
