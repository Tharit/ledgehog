<script lang="ts">
	import CheckIcon from '@lucide/svelte/icons/check';
	import InboxIcon from '@lucide/svelte/icons/inbox';
	import { formatCount } from '#lib/format/index.js';
	import FigureCard from '#lib/components/common/figure-card.svelte';

	// The review queue's count as the navigation shows it, split into the units to review and the
	// units that need an account, and a way into the queue. At zero: "All reviewed". `counts` is
	// null until the first read has answered.
	let {
		counts,
		locale = 'en'
	}: {
		counts: { pendingReview: number; needsAccount: number } | null;
		locale?: string;
	} = $props();

	const total = $derived(counts ? counts.pendingReview + counts.needsAccount : 0);
	const split = $derived(
		counts
			? [
					counts.pendingReview > 0 ? `${formatCount(counts.pendingReview, locale)} to review` : '',
					counts.needsAccount > 0
						? `${formatCount(counts.needsAccount, locale)} ${counts.needsAccount === 1 ? 'needs' : 'need'} an account`
						: ''
				]
					.filter((part) => part !== '')
					.join(' · ')
			: ''
	);
</script>

<FigureCard title="To review" loading={counts === null}>
	{#snippet figure()}
		{#if total === 0}
			<span class="inline-flex items-center gap-2" data-slot="all-reviewed">
				<CheckIcon size={28} strokeWidth={1.75} class="text-muted-foreground" aria-hidden="true" />
				<span class="text-xl">All reviewed</span>
			</span>
		{:else}
			<span class="inline-flex items-center gap-3">
				<InboxIcon size={28} strokeWidth={1.75} class="text-muted-foreground" aria-hidden="true" />
				<span class="amount">{formatCount(total, locale)}</span>
			</span>
		{/if}
	{/snippet}
	{#snippet rows()}
		{#if total > 0}
			<p class="text-sm text-muted-foreground">{split}</p>
			<a
				href="/review"
				class="w-fit rounded-sm text-sm font-medium text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
			>
				Open the review queue &rarr;
			</a>
		{/if}
	{/snippet}
</FigureCard>
