<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { cn } from '#lib/utils.js';

	let {
		title = 'Something went wrong',
		message,
		onretry,
		class: className
	}: { title?: string; message: string; onretry?: () => void; class?: string } = $props();
</script>

<div
	role="alert"
	class={cn(
		'flex max-w-md flex-col items-start gap-3 rounded-xl border bg-card p-5 shadow-card',
		className
	)}
>
	<h2 class="text-base font-semibold">{title}</h2>
	<p class="text-sm text-muted-foreground">{message}</p>
	{#if onretry}
		<Button variant="outline" onclick={onretry}>Try again</Button>
	{/if}
</div>
