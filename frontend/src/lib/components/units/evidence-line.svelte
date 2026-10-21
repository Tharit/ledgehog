<script lang="ts">
	import type { Evidence } from '#lib/units/evidence.js';
	import { cn } from '#lib/utils.js';

	// The basis of one value as a small line under it (patterns §4.3). A proposal is italic and
	// muted, the same everywhere (design §7); a rule links to its editor; a model's rationale is
	// part of the line and wraps.
	let { evidence, class: className }: { evidence: Evidence | null; class?: string } = $props();
</script>

{#if evidence}
	<span
		class={cn(
			'block text-xs break-words text-muted-foreground',
			evidence.proposal && 'italic',
			className
		)}
		data-slot="evidence"
		data-proposal={evidence.proposal || undefined}
	>
		{#if evidence.href}
			<a href={evidence.href} class="underline underline-offset-2 hover:text-foreground">
				{evidence.text}
			</a>
		{:else}
			{evidence.text}
		{/if}
	</span>
{/if}
