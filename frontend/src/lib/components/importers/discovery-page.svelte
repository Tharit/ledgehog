<script lang="ts">
	import ArrowLeftIcon from '@lucide/svelte/icons/arrow-left';
	import LoaderCircleIcon from '@lucide/svelte/icons/loader-circle';
	import { onDestroy, onMount } from 'svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import NoticeLine from '#lib/components/common/notice-line.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import InstanceFailure from '#lib/components/sync/instance-failure.svelte';
	import PromptDialog from '#lib/components/sync/prompt-dialog.svelte';
	import { IMPORTERS_PATH, instanceUrl } from '#lib/importers/links.js';
	import { DiscoveryStore } from '#lib/stores/discovery.svelte.js';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';
	import { session } from '#lib/stores/session.svelte.js';
	import { sync } from '#lib/stores/sync.svelte.js';
	import { viewMoment } from '#lib/sync/prompts.js';
	import DiscoveryRows from './discovery-rows.svelte';
	import LinkAccountDialog from './link-account-dialog.svelte';

	// Refresh accounts (ux/views/importers.md): what the login can reach at the bank, and what each is
	// here. The discovery is a task like a sync: while it runs this page says so and asks the PIN in
	// the same dialog (read from the store, so a prompt that arrived elsewhere is asked when this page
	// is shown); once it has ended the page reads the task's result; a failure is shown as a sync's.
	let { instanceId }: { instanceId: number } = $props();

	// made once per page: the route keys it by the instance
	const make = () => new DiscoveryStore(instanceId);
	const store = make();

	onMount(() => void store.init());
	onDestroy(() => store.dispose());
	// the result is read once the task has ended; opening an ended discovery reads it again
	$effect(() => {
		if (store.phase === 'ended') void store.read();
	});

	const label = $derived(store.instance?.label ?? 'the login');
	const locale = $derived(session.config?.locale ?? 'en');
	const timeZone = $derived(session.config?.timezone ?? 'UTC');
	const prompt = $derived(store.phase === 'running' ? sync.view.prompt : null);
	const moment = $derived(viewMoment(sync.view, () => null));
	const failure = $derived(store.failure);
	const linkable = $derived(
		[...lookupsStore.lookups.accounts.values()].filter((a) => a.closed_on === null)
	);
</script>

<div class="flex flex-col gap-4">
	<a
		href={instanceUrl(instanceId)}
		class="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground underline-offset-2 hover:underline"
	>
		<ArrowLeftIcon size={14} strokeWidth={1.75} aria-hidden="true" />
		{store.instance?.label ?? 'Importer'}
	</a>
	<PageHeader
		level={1}
		title="Refresh accounts"
		description={`What ${label} can reach at the bank, and what each is here.`}
	/>

	<NoticeLine notice={store.notice}>
		{#snippet action()}
			{#if store.notice?.action}
				<ActionButton variant="link" class="h-auto p-0" href={store.notice.action.path}>
					{store.notice.action.label}
				</ActionButton>
			{/if}
		{/snippet}
	</NoticeLine>

	{#if store.loadStatus === 'missing'}
		<ErrorState title="This importer does not exist" message="It may have been deleted." />
		<ActionButton variant="outline" href={IMPORTERS_PATH} class="w-fit">
			Back to the importers
		</ActionButton>
	{:else if store.loadStatus === 'error'}
		<ErrorState
			title="The importer could not be loaded"
			message="The server could not answer this request."
			onretry={() => store.init()}
		/>
	{:else if store.phase === 'running'}
		<p
			class="flex items-center gap-2 text-sm text-muted-foreground"
			aria-busy="true"
			data-slot="discovery-running"
		>
			<LoaderCircleIcon size={16} class="animate-spin" aria-hidden="true" />
			Looking up the accounts of {label}…
		</p>
	{:else if store.phase === 'ended' && failure}
		<InstanceFailure
			{instanceId}
			message={failure.message}
			stuck={!failure.retryable}
			canRunAgain={failure.retryable}
			runAgainLabel="Try again"
			onrunagain={() => void store.refresh()}
		/>
	{:else if store.phase === 'ended' && store.result}
		{#if store.result.accounts.length === 0}
			<p class="text-sm text-muted-foreground">{label} reaches no accounts at the bank.</p>
		{:else}
			<DiscoveryRows
				entries={store.result.accounts}
				lookups={lookupsStore.lookups}
				busyRefs={store.busyRefs}
				onlink={(entry, state) => store.openLink(entry, state)}
				onadd={(entry) => store.openAddAndLink(entry)}
			/>
		{/if}
	{:else if store.phase === 'ended' && store.resultStatus === 'loading'}
		<p class="text-sm text-muted-foreground" aria-busy="true">Reading what the bank reported…</p>
	{:else if store.phase === 'ended' && store.resultStatus === 'error'}
		<ErrorState
			title="The accounts could not be read"
			message="The server could not answer this request."
			onretry={() => store.read(true)}
		/>
	{:else if store.loadStatus === 'loading'}
		<p class="text-sm text-muted-foreground" aria-busy="true">Loading…</p>
	{:else}
		<!-- reached with no task (a reload after the end, an address), or one that was lost -->
		<div class="flex max-w-prose flex-col items-start gap-3 text-sm" data-slot="discovery-none">
			<p class="text-muted-foreground">
				{store.phase === 'interrupted' || store.resultStatus === 'lost' || store.phase === 'ended'
					? 'This lookup did not finish. Nothing was changed; ask the bank again.'
					: `Ask the bank which accounts ${label} can reach.`}
			</p>
			<ActionButton
				busy={store.starting}
				busyLabel="Starting…"
				disabled={!store.refreshable}
				reason={store.refreshable ? undefined : `${label} does not fetch accounts.`}
				onclick={() => void store.refresh()}
			>
				Refresh accounts
			</ActionButton>
		</div>
	{/if}
</div>

{#if prompt}
	{#key prompt.promptId}
		<PromptDialog
			{prompt}
			login={label}
			{moment}
			{timeZone}
			{locale}
			sending={sync.sending}
			fieldError={sync.fieldError}
			sendError={sync.sendError}
			canStop={false}
			onanswer={(value) => void sync.answer(value)}
			oncancel={() => void sync.cancelPrompt()}
		/>
	{/key}
{/if}

<LinkAccountDialog flow={store.link} accounts={linkable} {locale} />
