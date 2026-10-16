// State of the documents list page and of one document's page. The list is a SNAPSHOT like the
// ledger's (patterns §7): a changed filter refetches, nothing refreshes by itself, "load more"
// appends. Page-scoped: the page creates one and drops it. No domain computation here.
import { ApiError, DOCUMENT_PAGE_SIZE, getDocument, listDocuments } from '#lib/api/index.js';
import { todayIso } from '#lib/format/index.js';
import {
	describeDocumentFilter,
	documentFilterKey,
	emptyDocumentFilter,
	normalizeDocumentFilter
} from '#lib/documents/filter.js';
import type { Lookups } from '#lib/ledger/lookups.js';
import type { DocumentDetail, DocumentFilter, DocumentRow } from '#lib/types/domain.js';
import {
	documentProvidersStore,
	type DocumentProvidersStore
} from './document-providers.svelte.js';
import { lookupsStore, type LookupsStore } from './lookups.svelte.js';
import { session } from './session.svelte.js';

export type DocumentsStatus = 'loading' | 'ready' | 'error';

function asApiError(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

export class DocumentsStore {
	filter = $state.raw<DocumentFilter>(emptyDocumentFilter());
	documents = $state.raw<DocumentRow[]>([]);
	/** every document matching the filter, whatever the page */
	total = $state(0);
	status = $state<DocumentsStatus>('loading');
	error = $state.raw<ApiError | null>(null);
	loadingMore = $state(false);
	moreError = $state.raw<ApiError | null>(null);

	readonly #lookups: LookupsStore;
	get lookups(): Lookups {
		return this.#lookups.lookups;
	}
	get lookupsFailed(): string[] {
		return this.#lookups.failed;
	}

	readonly #providers: DocumentProvidersStore;

	constructor(
		lookups: LookupsStore = lookupsStore,
		providers: DocumentProvidersStore = documentProvidersStore
	) {
		this.#lookups = lookups;
		this.#providers = providers;
	}

	readonly locale = $derived(session.config?.locale ?? 'en');
	readonly baseCurrency = $derived(session.config?.base_currency ?? 'EUR');
	readonly today = $derived(todayIso(session.config?.timezone ?? 'UTC'));
	readonly activeFilters = $derived(
		describeDocumentFilter(this.filter, this.locale).map((part) => part.label)
	);
	/** the providers of the registered document importers, plus any chosen in the URL: what the provider chip offers */
	get providers(): string[] {
		return [...this.#providers.providers, ...this.filter.provider]
			.filter((provider, i, all) => all.indexOf(provider) === i)
			.sort();
	}

	#controller: AbortController | null = null;
	#generation = 0;
	#key: string | null = null;

	loadLookups(): Promise<void> {
		return this.#lookups.ensure();
	}

	loadProviders(): Promise<void> {
		return this.#providers.load();
	}

	/** Show this filter. The same filter as the one held does nothing (a URL echo). */
	applyFilter(next: DocumentFilter): void {
		const filter = normalizeDocumentFilter(next);
		const key = documentFilterKey(filter);
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
		this.documents = [];
		this.total = 0;
		try {
			const page = await listDocuments(this.filter, {
				limit: DOCUMENT_PAGE_SIZE,
				offset: 0,
				signal: controller.signal
			});
			if (generation !== this.#generation) return;
			this.documents = page.documents;
			this.total = page.total;
			this.status = 'ready';
		} catch (error) {
			if (generation !== this.#generation) return;
			this.error = asApiError(error);
			this.status = 'error';
		}
	}

	/** Append the next page (offset = documents held). */
	async loadMore(): Promise<void> {
		if (this.status !== 'ready' || this.loadingMore || this.documents.length >= this.total) return;
		const controller = new AbortController();
		this.#controller = controller;
		const generation = this.#generation;
		this.loadingMore = true;
		this.moreError = null;
		try {
			const page = await listDocuments(this.filter, {
				limit: DOCUMENT_PAGE_SIZE,
				offset: this.documents.length,
				signal: controller.signal
			});
			if (generation !== this.#generation) return;
			this.documents = [...this.documents, ...page.documents];
			this.total = page.total;
		} catch (error) {
			if (generation !== this.#generation) return;
			this.moreError = asApiError(error);
		} finally {
			if (generation === this.#generation) this.loadingMore = false;
		}
	}

	dispose(): void {
		this.#generation++;
		this.#controller?.abort();
	}
}

/** One document's page: the document with its lines and, when unlinked, the matches. */
export class DocumentDetailStore {
	status = $state<DocumentsStatus>('loading');
	document = $state.raw<DocumentDetail | null>(null);
	error = $state.raw<ApiError | null>(null);

	readonly #lookups: LookupsStore;
	get lookups(): Lookups {
		return this.#lookups.lookups;
	}
	readonly locale = $derived(session.config?.locale ?? 'en');

	constructor(lookups: LookupsStore = lookupsStore) {
		this.#lookups = lookups;
	}

	#controller: AbortController | null = null;
	#generation = 0;

	loadLookups(): Promise<void> {
		return this.#lookups.ensure();
	}

	async load(id: number): Promise<void> {
		this.#controller?.abort();
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		this.status = 'loading';
		this.error = null;
		this.document = null;
		try {
			const document = await getDocument(id, controller.signal);
			if (generation !== this.#generation) return;
			this.document = document;
			this.status = 'ready';
		} catch (error) {
			if (generation !== this.#generation) return;
			this.error = asApiError(error);
			this.status = 'error';
		}
	}

	dispose(): void {
		this.#generation++;
		this.#controller?.abort();
	}
}
