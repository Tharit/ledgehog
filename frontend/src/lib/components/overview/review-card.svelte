<script lang="ts">
	import CheckIcon from '@lucide/svelte/icons/check';
	import InboxIcon from '@lucide/svelte/icons/inbox';
	import { formatCount } from '#lib/format/index.js';
	import CardRow from '#lib/components/common/card-row.svelte';
	import FigureCard from '#lib/components/common/figure-card.svelte';

	// The review queue's count as the navigation shows it, the figure linking to the queue, and rows
	// for the units to review and the units that need an account. At zero: "All reviewed", no link
	// and no rows. `counts` is null until the first read has answered.
	let {
		counts,
		locale = 'en'
	}: {
		counts: { pendingReview: number; needsAccount: number } | null;
		locale?: string;
	} = $props();

	const total = $derived(counts ? counts.pendingReview + counts.needsAccount : 0);
</script>

<FigureCard
	title="To review"
	icon={total === 0 ? CheckIcon : InboxIcon}
	caption="Imported, not yet confirmed"
	loading={counts === null}
>
	{#snippet figure()}
		{#if total === 0}
			<span data-slot="all-reviewed">All reviewed</span>
		{:else}
			<a
				href="/review"
				class="rounded-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
			>
				<span class="amount">{formatCount(total, locale)}</span>
			</a>
		{/if}
	{/snippet}
	{#snippet rows()}
		{#if counts && total > 0}
			{#if counts.pendingReview > 0}
				<CardRow label="Ready to review">{formatCount(counts.pendingReview, locale)}</CardRow>
			{/if}
			{#if counts.needsAccount > 0}
				<CardRow label="Needs an account">{formatCount(counts.needsAccount, locale)}</CardRow>
			{/if}
		{/if}
	{/snippet}
</FigureCard>
