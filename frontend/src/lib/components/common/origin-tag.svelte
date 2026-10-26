<script lang="ts" module>
	export type Origin = 'import' | 'user' | 'booking';

	/** Who authored a row's source transaction, in the word the tag shows (patterns §4.1). */
	export const ORIGIN_LABELS: Readonly<Record<Origin, string>> = {
		import: 'Imported',
		user: 'Entered',
		booking: 'Booked'
	};
</script>

<script lang="ts">
	// The origin tag (patterns §4.1): a small muted tag on every row with a source transaction, in
	// the ledger list and in an account's statement. Nothing for a derived entry, which has none.
	let { origin }: { origin: Origin | null | undefined } = $props();
</script>

{#if origin}
	<span class="truncate text-xs text-muted-foreground" data-slot="origin-tag" data-origin={origin}
		>{ORIGIN_LABELS[origin]}</span
	>
{/if}
