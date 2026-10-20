<script lang="ts">
	import InfoIcon from '@lucide/svelte/icons/info';

	// The marker beside a savings rate whose period has unclassified entries, reconciliations or
	// unvalued amounts (spec §8): its income or spending may be incomplete. The sentence is the
	// tooltip and the accessible name.
	const SENTENCE =
		'This period has unclassified entries, reconciliations or unvalued amounts, so its income or spending may be incomplete.';
</script>

<span
	class="inline-flex text-muted-foreground"
	role="img"
	aria-label={SENTENCE}
	title={SENTENCE}
	data-slot="incomplete-marker"
>
	<InfoIcon size={16} strokeWidth={1.75} aria-hidden="true" />
</span>
