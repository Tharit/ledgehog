<script lang="ts">
	// An absent value ("Unclassified", "no description"): muted, dotted underline, the
	// explanation in a tooltip (design §7, patterns §9). Absent is neither zero nor blank.
	let { label, explanation }: { label: string; explanation: string } = $props();
</script>

<span
	class="text-muted-foreground underline decoration-dotted underline-offset-2"
	title={explanation}
	data-slot="absent-value">{label}</span
>
