// The account statement held by the account page: the pages fetched so far, newest first. It is a
// SNAPSHOT (patterns §7): nothing refreshes by itself and "load more" appends. Its one exception to
// *patch, don't refetch* (ux/views/account.md): after a write made from the page, `refetch`
// replaces every page held at once, because the write moved the balance of every row after it.
// The balances are the server's; nothing is computed here.
import { ApiError, DEFAULT_PAGE_SIZE, getStatement } from '#lib/api/index.js';
import type { StatementItem } from '#lib/types/domain.js';

/** the most rows one statement request may ask for */
const REFETCH_PAGE = 500;

export type StatementStatus = 'loading' | 'ready' | 'error';

function asApiError(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

export class StatementStore {
	accountId = $state<number | null>(null);
	items = $state.raw<StatementItem[]>([]);
	/** every item the account has, whatever the page */
	total = $state(0);
	status = $state<StatementStatus>('loading');
	error = $state.raw<ApiError | null>(null);
	loadingMore = $state(false);
	moreError = $state.raw<ApiError | null>(null);
	/** a refetch after a write is under way */
	refetching = $state(false);
	/** why the last refetch failed: the rows held stay, possibly out of date */
	refetchFailed = $state(false);

	#controller: AbortController | null = null;
	#generation = 0;

	/** Show another account (or the same one afresh): its first page. */
	async load(accountId: number): Promise<void> {
		this.#controller?.abort();
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		this.accountId = accountId;
		this.status = 'loading';
		this.error = null;
		this.moreError = null;
		this.loadingMore = false;
		this.refetching = false;
		this.refetchFailed = false;
		this.items = [];
		this.total = 0;
		try {
			const page = await getStatement(accountId, {
				limit: DEFAULT_PAGE_SIZE,
				offset: 0,
				signal: controller.signal
			});
			if (generation !== this.#generation) return;
			this.items = page.items;
			this.total = page.total;
			this.status = 'ready';
		} catch (error) {
			if (generation !== this.#generation) return;
			this.error = asApiError(error);
			this.status = 'error';
		}
	}

	/** Append the next page (offset = items held). */
	async loadMore(): Promise<void> {
		const accountId = this.accountId;
		if (accountId === null || this.status !== 'ready' || this.loadingMore) return;
		if (this.items.length >= this.total) return;
		const controller = new AbortController();
		this.#controller = controller;
		const generation = this.#generation;
		this.loadingMore = true;
		this.moreError = null;
		try {
			const page = await getStatement(accountId, {
				limit: DEFAULT_PAGE_SIZE,
				offset: this.items.length,
				signal: controller.signal
			});
			if (generation !== this.#generation) return;
			this.items = [...this.items, ...page.items];
			this.total = page.total;
		} catch (error) {
			if (generation !== this.#generation) return;
			this.moreError = asApiError(error);
		} finally {
			if (generation === this.#generation) this.loadingMore = false;
		}
	}

	/**
	 * Fetch the pages held again and swap them in, all at once: a write from this page moved the
	 * balance of every row after it. The rows are replaced whole (never patched), so the caller
	 * keeps its cursor by the identity of the row it acted on. Never fewer rows than a first page.
	 */
	async refetch(): Promise<void> {
		const accountId = this.accountId;
		if (accountId === null || this.status !== 'ready') return;
		this.#controller?.abort();
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		this.loadingMore = false;
		this.refetching = true;
		this.refetchFailed = false;
		const wanted = Math.max(this.items.length, DEFAULT_PAGE_SIZE);
		try {
			const fresh: StatementItem[] = [];
			let total = this.total;
			while (fresh.length < wanted) {
				const limit = Math.min(REFETCH_PAGE, wanted - fresh.length);
				const page = await getStatement(accountId, {
					limit,
					offset: fresh.length,
					signal: controller.signal
				});
				if (generation !== this.#generation) return;
				fresh.push(...page.items);
				total = page.total;
				if (page.items.length < limit) break;
			}
			this.items = fresh;
			this.total = total;
		} catch {
			if (generation !== this.#generation || controller.signal.aborted) return;
			this.refetchFailed = true;
		} finally {
			if (generation === this.#generation) this.refetching = false;
		}
	}

	dispose(): void {
		this.#controller?.abort();
		this.#generation++;
	}
}
