<script lang="ts">
	import { page } from '$app/state';
	import { onDestroy, onMount, untrack } from 'svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import PlanView from '#lib/components/sync/plan-view.svelte';
	import PromptDialog from '#lib/components/sync/prompt-dialog.svelte';
	import StopSyncDialog from '#lib/components/sync/stop-sync-dialog.svelte';
	import SyncProgress from '#lib/components/sync/sync-progress.svelte';
	import { refusalText } from '#lib/sync/entry.js';
	import { narrowingOf } from '#lib/sync/plan.js';
	import { viewMoment } from '#lib/sync/prompts.js';
	import type { AccountInfo } from '#lib/sync/progress.js';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';
	import { session } from '#lib/stores/session.svelte.js';
	import { sync } from '#lib/stores/sync.svelte.js';
	import { SyncPlanStore } from '#lib/stores/sync-plan.svelte.js';
	import type { SyncItem } from '#lib/types/domain.js';

	// The sync page (ux/views/sync.md): the states of one task. Nothing running: the plan. Running:
	// the progress, "Stop sync…" and, when the task is blocked, the prompt dialog. Ended: the report.
	// The task lives in the store, which outlives this page; the dialog reads the open prompt from it
	// when the page mounts, so a prompt that arrived elsewhere is asked on a later visit.
	const plan = new SyncPlanStore();
	let stopOpen = $state(false);
	let stopError = $state<string | null>(null);
	let stopBusy = $state(false);
	let notice = $state<string | null>(null);

	onMount(() => void lookupsStore.ensure());
	onDestroy(() => plan.dispose());

	$effect(() => {
		plan.narrowing = narrowingOf(page.url.search);
	});
	// the plan is read when the page opens and again whenever the task moves between its states
	$effect(() => {
		void sync.status;
		untrack(() => void plan.load());
	});
	// a decision about a task that has ended is moot, and must not come back with the next one
	$effect(() => {
		if (!active) stopOpen = false;
	});
	// opening this page clears the indicator's "Finished" line
	$effect(() => {
		if (sync.status === 'ended') sync.markSeen();
	});

	const locale = $derived(session.config?.locale ?? 'en');
	const timeZone = $derived(session.config?.timezone ?? 'UTC');
	const active = $derived(sync.status === 'attaching' || sync.status === 'running');
	const isSync = $derived(sync.kind === 'sync');
	const showProgress = $derived(isSync && (active || sync.status === 'ended'));
	const interrupted = $derived(sync.status === 'interrupted' && isSync);
	const discoveryRunning = $derived(sync.kind === 'discovery' && active);

	const accountOf = (id: number): AccountInfo | null => {
		const account = lookupsStore.lookups.accounts.get(id);
		return account
			? {
					name: account.name,
					icon: account.icon,
					color: account.color,
					kind: account.kind,
					currency: account.currency
				}
			: null;
	};
	const importerOf = (instanceId: number) =>
		plan.plan.find((i) => i.instance_id === instanceId)?.importer ?? null;

	const description = $derived.by(() => {
		const { instanceId, accountId } = plan.narrowing;
		if (instanceId === null || showProgress) return 'Fetch what your logins and sources have new.';
		const account = accountId === null ? null : accountOf(accountId);
		return `Fetching ${account?.name ?? plan.labelOf(instanceId)}.`;
	});

	// the dialog: only here, only while the prompt is open, read from the store
	const prompt = $derived(isSync && active ? sync.view.prompt : null);
	const moment = $derived(viewMoment(sync.view, (id) => accountOf(id)?.name ?? null));

	async function runAgain(items: SyncItem[]) {
		notice = null;
		const refusal = await sync.start(items);
		if (refusal) notice = refusalText(refusal);
	}

	async function stop() {
		stopBusy = true;
		stopError = null;
		const failure = await sync.abort();
		stopBusy = false;
		if (failure) stopError = failure;
		else stopOpen = false;
	}
</script>

<svelte:head>
	<title>Sync · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<PageHeader level={1} title="Sync" {description} />

	{#if notice}
		<Notice role="alert">{notice}</Notice>
	{/if}

	{#if showProgress}
		<SyncProgress
			view={sync.view}
			running={active}
			stopping={sync.stopping}
			labelOf={plan.labelOf}
			{importerOf}
			{accountOf}
			{locale}
			onstop={() => {
				stopError = null;
				stopOpen = true;
			}}
			onback={() => sync.reset()}
			onrunagain={runAgain}
		/>
	{:else if interrupted}
		<EmptyState
			title="This sync was interrupted"
			actionLabel="Back to the plan"
			onaction={() => sync.reset()}
		>
			What was fetched is kept; run it again.
		</EmptyState>
	{:else if discoveryRunning}
		<Notice>
			Refreshing the accounts of a login.
			{#snippet action()}
				<ActionButton variant="link" class="h-auto p-0" href={sync.homePath}>Open it</ActionButton>
			{/snippet}
		</Notice>
	{:else}
		<PlanView
			plan={plan.visible}
			status={plan.status}
			narrowed={plan.narrowing.instanceId !== null}
			{accountOf}
			bind:starts={plan.starts}
			refusal={plan.refusal}
			starting={plan.starting}
			{locale}
			onstart={() => plan.begin((items) => sync.start(items))}
			onretry={() => plan.load()}
		/>
	{/if}
</div>

{#if prompt}
	{#key prompt.promptId}
		<PromptDialog
			{prompt}
			login={plan.labelOf(prompt.instanceId)}
			{moment}
			{timeZone}
			{locale}
			sending={sync.sending}
			fieldError={sync.fieldError}
			sendError={sync.sendError}
			canStop={true}
			onanswer={(value) => void sync.answer(value)}
			oncancel={() => void sync.cancelPrompt()}
			onstop={() => {
				stopError = null;
				stopOpen = true;
			}}
		/>
	{/key}
{/if}

<StopSyncDialog
	open={stopOpen && active}
	busy={stopBusy}
	error={stopError}
	onclose={() => (stopOpen = false)}
	onstop={() => void stop()}
/>
