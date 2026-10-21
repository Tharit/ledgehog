<script lang="ts">
	import SparklesIcon from '@lucide/svelte/icons/sparkles';

	// The model is looking: a small, quiet mark (design §7 vocabulary: muted, a tooltip, an accessible
	// name equal to it). It pulses softly; under reduced motion it stands still.
	let { label, size = 14 }: { label: string; size?: number } = $props();
</script>

<span
	class="inline-flex shrink-0 animate-pulse text-muted-foreground motion-reduce:animate-none"
	title={label}
	role="img"
	aria-label={label}
	data-slot="model-activity"
>
	<SparklesIcon {size} strokeWidth={1.75} aria-hidden="true" />
</span>
