<script lang="ts" module>
	import type { IconComponent } from '#lib/theme/icons.js';
	import CircleDashedIcon from '@lucide/svelte/icons/circle-dashed';
	import CircleQuestionMarkIcon from '@lucide/svelte/icons/circle-question-mark';
	import ClockIcon from '@lucide/svelte/icons/clock';
	import UnlinkIcon from '@lucide/svelte/icons/unlink';

	// One badge per review token and nothing else (patterns §4.2).
	export const REVIEW_BADGE_ICONS: Record<string, IconComponent> = {
		unconfirmed: CircleDashedIcon,
		unclassified: CircleQuestionMarkIcon,
		waiting: ClockIcon,
		unmatched_transfer: UnlinkIcon
	};
</script>

<script lang="ts">
	import { REVIEW_FLAG_INFO, reviewSentence, type BadgeSubject } from '#lib/ledger/review.js';

	// The sentence is the tooltip; the name and the sentence are the accessible label. The entry,
	// when given, decides the words of `waiting` on a transfer leg.
	let { flag, entry = null }: { flag: string; entry?: BadgeSubject | null } = $props();

	const Icon = $derived(REVIEW_BADGE_ICONS[flag]);
	const info = $derived(REVIEW_FLAG_INFO[flag]);
	const sentence = $derived(reviewSentence(flag, entry) ?? info?.sentence ?? '');
</script>

{#if Icon && info}
	<span
		class="inline-flex shrink-0 text-muted-foreground"
		title={sentence}
		role="img"
		aria-label={`${info.name}: ${sentence}`}
		data-flag={flag}
	>
		<Icon size={14} strokeWidth={1.75} />
	</span>
{/if}
