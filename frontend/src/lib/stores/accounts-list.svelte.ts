// The accounts list page (`/accounts`): every account with its balance and facts, fetched afresh
// on every visit (the facts move with every write, elsewhere too) and handed to the shared lookups.
import { ApiError, listAccounts } from '#lib/api/index.js';
import { orderAccounts } from '#lib/accounts/list.js';
import { todayIso } from '#lib/format/index.js';
import type { Account } from '#lib/types/domain.js';
import { lookupsStore } from './lookups.svelte.js';
import { session } from './session.svelte.js';

export class AccountsListStore {
	accounts = $state.raw<Account[]>([]);
	status = $state<'loading' | 'ready' | 'error'>('loading');
	error = $state.raw<ApiError | null>(null);

	readonly locale = $derived(session.config?.locale ?? 'en');
	readonly today = $derived(todayIso(session.config?.timezone ?? 'UTC'));

	#generation = 0;

	async load(): Promise<void> {
		const generation = ++this.#generation;
		this.status = 'loading';
		this.error = null;
		try {
			const all = await listAccounts();
			if (generation !== this.#generation) return;
			lookupsStore.setAccounts(all);
			this.accounts = orderAccounts(all);
			this.status = 'ready';
		} catch (error) {
			if (generation !== this.#generation) return;
			this.error =
				error instanceof ApiError
					? error
					: new ApiError(0, 'network_error', 'The server could not be reached.');
			this.status = 'error';
		}
	}

	dispose(): void {
		this.#generation++;
	}
}
