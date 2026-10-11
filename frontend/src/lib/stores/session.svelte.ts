// Who is signed in, and the deployment's read-only configuration. App-wide by nature: every
// route needs it, and an ended session (a 401 anywhere) must reach the shell.

import {
	ApiError,
	getConfig,
	login,
	logout,
	me,
	setUnauthenticatedHandler,
	type AppConfig,
	type SessionUser
} from '#lib/api/index.js';

export type SessionStatus = 'loading' | 'authenticated' | 'anonymous' | 'error';

class SessionStore {
	status = $state<SessionStatus>('loading');
	user = $state<SessionUser | null>(null);
	config = $state<AppConfig | null>(null);
	/** Why the start failed, when `status` is `error` (the server is down, say). */
	error = $state<ApiError | null>(null);

	/** Load the user and the configuration; an unauthenticated answer means "anonymous". */
	async start(): Promise<void> {
		setUnauthenticatedHandler(() => this.expire());
		this.status = 'loading';
		this.error = null;
		try {
			this.user = await me();
			this.config = await getConfig();
			this.status = 'authenticated';
		} catch (error) {
			if (error instanceof ApiError && error.code === 'unauthenticated') {
				this.expire();
			} else {
				this.error =
					error instanceof ApiError
						? error
						: new ApiError(0, 'network_error', 'The server could not be reached.');
				this.status = 'error';
			}
		}
	}

	/** Sign in; a refusal (`invalid_credentials`) is thrown for the form to show. */
	async signIn(loginName: string, password: string): Promise<void> {
		this.user = await login(loginName, password);
		this.config = await getConfig();
		this.status = 'authenticated';
	}

	async signOut(): Promise<void> {
		await logout();
		this.expire();
	}

	/** The session has ended: back to anonymous, nothing of the user kept. */
	expire(): void {
		this.user = null;
		this.config = null;
		this.error = null;
		this.status = 'anonymous';
	}
}

export const session = new SessionStore();
