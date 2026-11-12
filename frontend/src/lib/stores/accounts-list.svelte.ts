// The accounts list page (`/accounts`): every account with its balance and facts, grouped by kind
// with each group's sums, fetched afresh on every visit (the facts move with every write,
// elsewhere too) and handed to the shared lookups.
import { ApiError, listAccountGroups } from '#lib/api/index.js';
import { groupAccounts, type ListGroup } from '#lib/accounts/list.js';
import { todayIso } from '#lib/format/index.js';
import { lookupsStore } from './lookups.svelte.js';
import { session } from './session.svelte.js';

export class AccountsListStore {
	/** the accounts, grouped by kind with the closed ones last */
	groups = $state.raw<ListGroup[]>([]);
	status = $state<'loading' | 'ready' | 'error'>('loading');
	error = $state.raw<ApiError | null>(null);

	readonly locale = $derived(session.config?.locale ?? 'en');
	readonly today = $derived(todayIso(session.config?.timezone ?? 'UTC'));

	#generation = 0;

	async load(): Promise<void> {
		const generation = ++this.#generation;
		// a list already shown is replaced when the answer comes (a refetch when a sync ends)
		if (this.status === 'error') this.status = 'loading';
		this.error = null;
		try {
			const list = await listAccountGroups();
			if (generation !== this.#generation) return;
			lookupsStore.setAccounts(list.accounts);
			this.groups = groupAccounts(list.accounts, list.groups);
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
