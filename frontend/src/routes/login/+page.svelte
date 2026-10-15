<script lang="ts">
	import { ApiError } from '#lib/api/index.js';
	import LoginForm from '#lib/components/auth/login-form.svelte';
	import { session } from '#lib/stores/session.svelte.js';

	// Shown by the error code, never by the server's message (architecture §4.4).
	const MESSAGES: Record<string, string> = {
		invalid_credentials: 'Wrong login or password.',
		network_error: 'The server could not be reached.'
	};

	let pending = $state(false);
	let error = $state<string | null>(null);

	async function submit(login: string, password: string) {
		pending = true;
		error = null;
		try {
			await session.signIn(login, password); // the shell then moves on to /ledger
		} catch (e) {
			error = (e instanceof ApiError && MESSAGES[e.code]) || 'Something went wrong.';
		} finally {
			pending = false;
		}
	}
</script>

<svelte:head>
	<title>Log in · Ledgehog</title>
</svelte:head>

<div class="grid min-h-screen place-items-center p-4">
	<div class="flex w-full max-w-sm flex-col items-center gap-6">
		<img src="/brand/mascot.png" alt="" width="128" height="135" class="h-auto w-32" />
		<LoginForm {pending} {error} onsubmit={submit} />
	</div>
</div>
