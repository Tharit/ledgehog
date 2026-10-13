<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import NoticeLine from '#lib/components/common/notice-line.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import type { TagsStore } from '#lib/tags/store.svelte.js';
	import type { Tag } from '#lib/types/domain.js';
	import TagAddDialog from './tag-add-dialog.svelte';
	import TagDeleteDialog from './tag-delete-dialog.svelte';
	import TagRow from './tag-row.svelte';

	// The tags screen (spec §3.7): tags mark entries across categories. They are added here or
	// from the ledger; here they are also renamed, recoloured and deleted. Adding is a form
	// dialog, rename is in place and deleting is a decision (patterns §11).
	let { store }: { store: TagsStore } = $props();

	onMount(() => void store.load());

	let addOpen = $state(false);

	// the tag being deleted stays while the dialog closes
	let deleteOpen = $state(false);
	let deleting = $state<Tag | null>(null);

	// a new tag is revealed, marked briefly and focused
	let revealedId = $state<number | null>(null);
	let focusRevealed = $state(false);
	let revealTimer: ReturnType<typeof setTimeout> | undefined;

	function added(tag: Tag) {
		addOpen = false;
		revealedId = tag.id;
		focusRevealed = false;
		clearTimeout(revealTimer);
		revealTimer = setTimeout(() => (revealedId = null), 2500);
	}
	onDestroy(() => clearTimeout(revealTimer));
</script>

<div class="flex flex-col gap-4">
	<PageHeader
		title="Tags"
		description="Tags mark entries across categories, for example a holiday."
		actionLabel="Add tag"
		onaction={() => (addOpen = true)}
		actionDisabled={store.status !== 'ready'}
	/>

	<NoticeLine notice={store.notice} />

	{#if store.status === 'loading'}
		<div aria-busy="true" aria-label="Loading tags" data-slot="tags-loading">
			{#each [0, 1, 2, 3, 4] as i (i)}
				<div class="flex h-12 items-center gap-3 border-b border-border">
					<div class="size-8 shrink-0 animate-pulse rounded-full bg-muted"></div>
					<div
						class="h-3 animate-pulse rounded bg-muted"
						style:width={`${30 + ((i * 17) % 30)}%`}
					></div>
				</div>
			{/each}
		</div>
	{:else if store.status === 'error' && store.error}
		<ErrorState
			title="The tags could not be loaded"
			message={store.error.message}
			onretry={() => store.load()}
		/>
	{:else if store.tags.length === 0}
		<EmptyState title="No tags yet" actionLabel="Add tag" onaction={() => (addOpen = true)}>
			Tags mark entries across categories, for example a holiday: add one here or from the ledger.
		</EmptyState>
	{:else}
		<ul aria-label="Tags">
			{#each store.tags as tag (tag.id)}
				<TagRow
					{tag}
					{store}
					revealed={tag.id === revealedId}
					focus={focusRevealed && tag.id === revealedId}
					ondelete={() => {
						deleting = tag;
						deleteOpen = true;
					}}
				/>
			{/each}
		</ul>
	{/if}
</div>

<TagAddDialog
	{store}
	open={addOpen}
	onclose={() => (addOpen = false)}
	onsaved={added}
	onclosedafteradd={() => (focusRevealed = true)}
/>
<TagDeleteDialog {store} open={deleteOpen} tag={deleting} onclose={() => (deleteOpen = false)} />
