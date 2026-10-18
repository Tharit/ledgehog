<script lang="ts">
	import ActionButton from '#lib/components/common/action-button.svelte';
	import type { TaskView } from '#lib/sync/events.js';
	import type { AccountInfo } from '#lib/sync/progress.js';
	import { endLines } from '#lib/sync/status.js';
	import type { SyncItem } from '#lib/types/domain.js';
	import InstanceCard from './instance-card.svelte';

	// The running page and the report of an ended sync (ux/views/sync.md "Progress and report"): one
	// card per login in the order the sync takes them. While it runs, "Stop sync…" (and "Stopping…"
	// once asked); when it has ended, one line says how it ended, and "Back to the plan".
	let {
		view,
		running,
		stopping = false,
		labelOf,
		importerOf = () => null,
		accountOf = () => null,
		locale = 'en',
		onstop,
		onback,
		onrunagain
	}: {
		view: TaskView;
		running: boolean;
		stopping?: boolean;
		labelOf: (instanceId: number) => string;
		importerOf?: (instanceId: number) => string | null;
		accountOf?: (accountId: number) => AccountInfo | null;
		locale?: string;
		onstop?: () => void;
		onback?: () => void;
		onrunagain?: (items: SyncItem[]) => void;
	} = $props();

	const lines = $derived(view.end ? endLines(view.end, labelOf) : []);
</script>

<section class="flex flex-col gap-3" data-slot="sync-progress" aria-label="Sync progress">
	{#if running}
		<div class="flex flex-wrap items-center justify-between gap-3">
			<p class="text-sm text-muted-foreground" role="status" data-slot="sync-state">
				{stopping ? 'Stopping…' : 'Syncing…'}
			</p>
			<ActionButton variant="outline" disabled={stopping} onclick={onstop}>Stop sync…</ActionButton>
		</div>
	{:else if view.end}
		<div class="flex flex-wrap items-center justify-between gap-3" data-slot="sync-end">
			<div class="flex flex-col gap-0.5 text-sm">
				{#each lines as line, i (i)}
					<p class={i === 0 ? 'font-medium' : 'text-muted-foreground'}>{line}</p>
				{/each}
			</div>
			<ActionButton variant="outline" onclick={onback}>Back to the plan</ActionButton>
		</div>
	{/if}

	{#each view.instances as instance (instance.instanceId)}
		<InstanceCard
			{instance}
			label={labelOf(instance.instanceId)}
			importer={importerOf(instance.instanceId)}
			prompt={view.prompt}
			ended={view.end !== null}
			{accountOf}
			{locale}
			{onrunagain}
		/>
	{/each}
</section>
