<script lang="ts" module>
	import type { IconComponent } from '#lib/theme/icons.js';
	import CircleDashedIcon from '@lucide/svelte/icons/circle-dashed';
	import CircleQuestionMarkIcon from '@lucide/svelte/icons/circle-question-mark';
	import FileTextIcon from '@lucide/svelte/icons/file-text';
	import ClockIcon from '@lucide/svelte/icons/clock';
	import UnlinkIcon from '@lucide/svelte/icons/unlink';

	// One badge per review token and nothing else (patterns §4.2).
	export const REVIEW_BADGE_ICONS: Record<string, IconComponent> = {
		unconfirmed: CircleDashedIcon,
		unclassified: CircleQuestionMarkIcon,
		document_suggested: FileTextIcon,
		waiting: ClockIcon,
		unmatched_transfer: UnlinkIcon
	};
</script>

<script lang="ts">
	import { REVIEW_FLAG_INFO } from '#lib/ledger/review.js';

	// The sentence is the tooltip; the name and the sentence are the accessible label.
	let { flag }: { flag: string } = $props();

	const Icon = $derived(REVIEW_BADGE_ICONS[flag]);
	const info = $derived(REVIEW_FLAG_INFO[flag]);
</script>

{#if Icon && info}
	<span
		class="inline-flex shrink-0 text-muted-foreground"
		title={info.sentence}
		role="img"
		aria-label={`${info.name}: ${info.sentence}`}
		data-flag={flag}
	>
		<Icon size={14} strokeWidth={1.75} />
	</span>
{/if}
