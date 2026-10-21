<script lang="ts">
	import ActionButton from '#lib/components/common/action-button.svelte';
	import Field from '#lib/components/common/field.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import Notice from '#lib/components/common/notice.svelte';

	let {
		pending = false,
		error = null,
		sso = false,
		passwordLogin = true,
		onsubmit
	}: {
		pending?: boolean;
		error?: string | null;
		/** offer "Log in with SSO" (a full navigation to the provider's sign-in) */
		sso?: boolean;
		/** offer the login and password fields; off when OIDC is enforced */
		passwordLogin?: boolean;
		onsubmit: (login: string, password: string) => void;
	} = $props();

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
	{#if passwordLogin}
		<Field label="Login">
			{#snippet children(control)}
				<Input {...control} name="login" autocomplete="username" required bind:value={login} />
			{/snippet}
		</Field>
		<Field label="Password">
			{#snippet children(control)}
				<Input
					{...control}
					name="password"
					type="password"
					autocomplete="current-password"
					required
					bind:value={password}
				/>
			{/snippet}
		</Field>
	{/if}
	{#if error}
		<Notice role="alert">{error}</Notice>
	{/if}
	{#if passwordLogin}
		<ActionButton type="submit" busy={pending} busyLabel="Logging in…">Log in</ActionButton>
	{/if}
	{#if sso}
		<!-- a full navigation: the server redirects to the provider and back -->
		<ActionButton
			variant={passwordLogin ? 'outline' : 'primary'}
			href="/api/session/oidc"
			data-sveltekit-reload>Log in with SSO</ActionButton
		>
	{/if}
</form>
