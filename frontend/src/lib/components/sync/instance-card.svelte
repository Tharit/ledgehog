<script lang="ts">
	import {
		canRunAgain,
		runAgainItems,
		stuckFailures,
		type OpenPrompt,
		type TaskInstance
	} from '#lib/sync/events.js';
	import Card from '#lib/components/common/card.svelte';
	import type { AccountInfo } from '#lib/sync/progress.js';
	import type { SyncItem } from '#lib/types/domain.js';
	import InstanceFailure from './instance-failure.svelte';
	import ItemRow from './item-row.svelte';

	// One login of a running or ended sync (ux/views/sync.md "Progress and report"): its label and
	// where it stands on the right, one row per item below, and, once, the login's own error with its
	// next step. "Run again" appears when the sync is over, since a second sync cannot start before.
	let {
		instance,
		label,
		importer = null,
		prompt = null,
		ended = false,
		accountOf = () => null,
		locale = 'en',
		onrunagain
	}: {
		instance: TaskInstance;
		label: string;
		importer?: string | null;
		/** the open prompt of the task, if any: it marks the login or the row it belongs to */
		prompt?: OpenPrompt | null;
		/** the whole task has ended */
		ended?: boolean;
		accountOf?: (accountId: number) => AccountInfo | null;
		locale?: string;
		onrunagain?: (items: SyncItem[]) => void;
	} = $props();

	const asking = $derived(prompt !== null && prompt.instanceId === instance.instanceId);
	const stateText = $derived.by(() => {
		if (asking && prompt?.runId === null) return 'Needs your input';
		switch (instance.state) {
			case 'queued':
				return 'Waiting';
			case 'signing_in':
				return 'Signing in…';
			case 'working':
				return 'Fetching…';
			case 'not_started':
				return 'Not started';
			default:
				return null;
		}
	});
	const stuck = $derived(stuckFailures(instance).length > 0);
	const again = $derived(ended && canRunAgain(instance));
</script>

<Card
	element="section"
	class="flex flex-col gap-1"
	data-slot="instance-card"
	data-state={instance.state}
	aria-label={label}
>
	<div class="flex flex-wrap items-baseline justify-between gap-x-3">
		<h2 class="text-sm font-semibold">
			{label}
			{#if importer}<span class="font-normal text-muted-foreground">· {importer}</span>{/if}
		</h2>
		{#if stateText}
			<span class="text-sm text-muted-foreground" data-slot="instance-state">{stateText}</span>
		{/if}
	</div>
	{#if instance.items.length > 0}
		<ul class="flex flex-col">
			{#each instance.items as item, i (i)}
				<ItemRow
					{item}
					instanceId={instance.instanceId}
					account={item.accountId === null ? null : accountOf(item.accountId)}
					waiting={asking && item.runId !== null && prompt?.runId === item.runId}
					{locale}
				/>
			{/each}
		</ul>
	{/if}
	{#if instance.failure?.message || stuck || again}
		<InstanceFailure
			instanceId={instance.instanceId}
			message={instance.failure?.message ?? null}
			{stuck}
			canRunAgain={again}
			onrunagain={() => onrunagain?.(runAgainItems(instance))}
		/>
	{/if}
</Card>
