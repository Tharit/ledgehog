<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { ApiError, getConfig } from '#lib/api/index.js';
	import LoginForm from '#lib/components/auth/login-form.svelte';
	import { session } from '#lib/stores/session.svelte.js';

	// Shown by the error code, never by the server's message (architecture §4.4). The `oidc_*` codes
	// come back from the provider's return as `/login?error=<code>` (architecture §5.6).
	const MESSAGES: Record<string, string> = {
		invalid_credentials: 'Wrong login or password.',
		password_login_disabled: 'Signing in with a password is turned off. Use SSO.',
		network_error: 'The server could not be reached.',
		oidc_not_allowed: 'Your account is not allowed to use Ledgehog.',
		oidc_disabled: 'This account is disabled.',
		oidc_unverified: 'The identity provider has not verified your e-mail address.',
		oidc_no_login: 'The identity provider did not send what is needed to identify you.',
		oidc_unavailable: 'The identity provider could not be reached.',
		oidc_failed: 'Signing in with SSO did not work. Please try again.'
	};

	let pending = $state(false);
	let submitError = $state<string | null>(null);
	let sso = $state(false);
	let enforced = $state(false);

	// What came back from a refused SSO sign-in, in plain words.
	const returned = $derived.by(() => {
		const code = page.url?.searchParams.get('error');
		return code ? (MESSAGES[code] ?? 'Something went wrong.') : null;
	});
	const error = $derived(submitError ?? returned);

	onMount(async () => {
		try {
			const config = await getConfig(); // needs no session
			sso = config.oidc_offered;
			enforced = config.oidc_enforced;
		} catch {
			// the password form stays: a server that cannot answer cannot sign anyone in anyway
		}
	});

	async function submit(login: string, password: string) {
		pending = true;
		submitError = null;
		try {
			await session.signIn(login, password); // the shell then moves on to /ledger
		} catch (e) {
			submitError = (e instanceof ApiError && MESSAGES[e.code]) || 'Something went wrong.';
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
		<LoginForm {pending} {error} {sso} passwordLogin={!enforced} onsubmit={submit} />
	</div>
</div>
