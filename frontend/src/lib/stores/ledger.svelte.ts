// State of the ledger list page: the filter, the page of entries held, the lookups the rows
// resolve ids against. The list is a SNAPSHOT (patterns §7): a changed filter refetches, nothing
// refreshes by itself, and "load more" appends. Page-scoped: the page creates one and drops it.
// No domain computation here: what a row shows comes from the API.

import {
	ApiError,
	DEFAULT_PAGE_SIZE,
	listAccounts,
	listCategories,
	listEntries,
	listPayees,
	listTags
} from '#lib/api/index.js';
import { todayIso } from '#lib/format/index.js';
import { describeFilter } from '#lib/ledger/describe.js';
import {
	emptyFilter,
	filterKey,
	normalizeFilter,
	type LedgerFilterState
} from '#lib/ledger/filter.js';
import { buildLookups, emptyLookups, type Lookups } from '#lib/ledger/lookups.js';
import type { Entry } from '#lib/types/domain.js';
import { session } from './session.svelte.js';

export type LedgerStatus = 'loading' | 'ready' | 'error';

function asApiError(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

export class LedgerStore {
	filter = $state.raw<LedgerFilterState>(emptyFilter());
	entries = $state.raw<Entry[]>([]);
	/** every entry matching the filter, whatever the page */
	total = $state(0);
	status = $state<LedgerStatus>('loading');
	/** why the first page failed (status `error`) */
	error = $state.raw<ApiError | null>(null);
	loadingMore = $state(false);
	/** why "load more" failed; the entries held stay */
	moreError = $state.raw<ApiError | null>(null);

	lookups = $state.raw<Lookups>(emptyLookups());
	/** the lists that could not be loaded (their names), shown as a quiet notice */
	lookupsFailed = $state.raw<string[]>([]);

	readonly locale = $derived(session.config?.locale ?? 'en');
	readonly baseCurrency = $derived(session.config?.base_currency ?? 'EUR');
	readonly today = $derived(todayIso(session.config?.timezone ?? 'UTC'));
	/** the active filters in words, for the empty state */
	readonly activeFilters = $derived(
		describeFilter(this.filter, { lookups: this.lookups, locale: this.locale }).map((p) => p.label)
	);
	/** more than one account can appear: the account column is shown */
	readonly showAccount = $derived(
		this.filter.account_id.length !== 1 && this.lookups.accounts.size !== 1
	);

	#controller: AbortController | null = null;
	#generation = 0;
	#key: string | null = null;
	#lookupsRequested = false;

	/** Show this filter. The same filter as the one held does nothing (a URL echo). */
	applyFilter(next: LedgerFilterState): void {
		const filter = normalizeFilter(next);
		const key = filterKey(filter);
		if (key === this.#key) return;
		this.#key = key;
		this.filter = filter;
		void this.reload();
	}

	/** Fetch the first page again for the current filter. */
	async reload(): Promise<void> {
		this.#controller?.abort();
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		this.status = 'loading';
		this.error = null;
		this.moreError = null;
		this.loadingMore = false;
		this.entries = [];
		this.total = 0;
		try {
			const page = await listEntries(this.filter, {
				limit: DEFAULT_PAGE_SIZE,
				offset: 0,
				signal: controller.signal
			});
			if (generation !== this.#generation) return;
			this.entries = page.entries;
			this.total = page.total;
			this.status = 'ready';
		} catch (error) {
			if (generation !== this.#generation) return; // superseded by a newer fetch
			this.error = asApiError(error);
			this.status = 'error';
		}
	}

	/** Append the next page (offset += entries held). */
	async loadMore(): Promise<void> {
		if (this.status !== 'ready' || this.loadingMore || this.entries.length >= this.total) return;
		const controller = new AbortController();
		this.#controller = controller;
		const generation = this.#generation;
		this.loadingMore = true;
		this.moreError = null;
		try {
			const page = await listEntries(this.filter, {
				limit: DEFAULT_PAGE_SIZE,
				offset: this.entries.length,
				signal: controller.signal
			});
			if (generation !== this.#generation) return;
			this.entries = [...this.entries, ...page.entries];
			this.total = page.total;
		} catch (error) {
			if (generation !== this.#generation) return;
			this.moreError = asApiError(error);
		} finally {
			if (generation === this.#generation) this.loadingMore = false;
		}
	}

	/** Load the lists rows resolve ids against, once. A list that fails is simply empty. */
	async loadLookups(): Promise<void> {
		if (this.#lookupsRequested) return;
		this.#lookupsRequested = true;
		const names = ['accounts', 'categories', 'payees', 'tags'];
		const results = await Promise.allSettled([
			listAccounts(),
			listCategories(),
			listPayees(),
			listTags()
		]);
		const value = <T>(result: PromiseSettledResult<T[]>): T[] =>
			result.status === 'fulfilled' ? result.value : [];
		this.lookups = buildLookups({
			accounts: value(results[0]),
			categories: value(results[1]),
			payees: value(results[2]),
			tags: value(results[3])
		});
		this.lookupsFailed = names.filter((_, i) => results[i].status === 'rejected');
	}

	/** The page is going away: nothing more may land in the store. */
	dispose(): void {
		this.#generation++;
		this.#controller?.abort();
		this.#controller = null;
	}
}
