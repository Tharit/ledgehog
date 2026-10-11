<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import Notice from '#lib/components/common/notice.svelte';

	let {
		pending = false,
		error = null,
		onsubmit
	}: {
		pending?: boolean;
		error?: string | null;
		onsubmit: (login: string, password: string) => void;
	} = $props();

	const id = $props.id();
	let login = $state('');
	let password = $state('');

	function submit(event: SubmitEvent) {
		event.preventDefault();
		onsubmit(login.trim(), password);
	}
</script>

<form
	class="flex w-full max-w-sm flex-col gap-4 rounded-xl border bg-card p-5 shadow-card"
	onsubmit={submit}
>
	<!-- Placeholder wordmark: the raster mascot must be redrawn as SVG before it ships (design §9). -->
	<h1 class="text-[28px] font-semibold text-primary">Ledgehog</h1>
	<div class="flex flex-col gap-1.5">
		<label for="{id}-login" class="text-xs font-medium text-muted-foreground">Login</label>
		<Input id="{id}-login" name="login" autocomplete="username" required bind:value={login} />
	</div>
	<div class="flex flex-col gap-1.5">
		<label for="{id}-pw" class="text-xs font-medium text-muted-foreground">Password</label>
		<Input
			id="{id}-pw"
			name="password"
			type="password"
			autocomplete="current-password"
			required
			bind:value={password}
		/>
	</div>
	{#if error}
		<Notice role="alert">{error}</Notice>
	{/if}
	<Button type="submit" size="lg" disabled={pending}>Log in</Button>
</form>
