<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import Card from './card.svelte';
	import { cn } from '#lib/utils.js';

	let {
		title = 'Something went wrong',
		message,
		onretry,
		class: className
	}: { title?: string; message: string; onretry?: () => void; class?: string } = $props();
</script>

<Card role="alert" class={cn('flex max-w-md flex-col items-start gap-3', className)}>
	<h2 class="text-base font-semibold">{title}</h2>
	<p class="text-sm text-muted-foreground">{message}</p>
	{#if onretry}
		<Button variant="outline" onclick={onretry}>Try again</Button>
	{/if}
</Card>
