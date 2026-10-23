import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getDocument, listDocuments } from '#lib/api/index.js';
import { documentDetail, documentRow } from '#lib/documents/fixtures.js';
import { emptyDocumentFilter } from '#lib/documents/filter.js';
import { DocumentProvidersStore } from './document-providers.svelte.js';
import { LookupsStore } from './lookups.svelte.js';
import { DocumentDetailStore, DocumentsStore } from './documents.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listDocuments: vi.fn(),
	readChanges: vi.fn(),
	getDocument: vi.fn(),
	listDocumentProviders: vi.fn(),
	listAccounts: vi.fn(async () => []),
	listCategories: vi.fn(async () => []),
	listPayees: vi.fn(async () => []),
	listTags: vi.fn(async () => [])
}));

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function page(ids: number[], total: number) {
	return { documents: ids.map((id) => documentRow({ id })), total, limit: 100, offset: 0 };
}

beforeEach(() => vi.resetAllMocks());

describe('DocumentsStore', () => {
	it('fetches the first page for a filter and holds it', async () => {
		vi.mocked(listDocuments).mockResolvedValue(page([3, 2, 1], 3));
		const store = new DocumentsStore(new LookupsStore());

		store.applyFilter({ ...emptyDocumentFilter(), provider: ['amazon'] });
		expect(store.status).toBe('loading');
		await flush();

		expect(store.status).toBe('ready');
		expect(store.documents.map((d) => d.id)).toEqual([3, 2, 1]);
		expect(vi.mocked(listDocuments).mock.calls[0][0].provider).toEqual(['amazon']);
		expect(store.activeFilters).toEqual(['amazon']);
	});

	it('does nothing for the same filter again (a URL echo)', async () => {
		vi.mocked(listDocuments).mockResolvedValue(page([1], 1));
		const store = new DocumentsStore(new LookupsStore());
		store.applyFilter(emptyDocumentFilter());
		store.applyFilter({ ...emptyDocumentFilter(), q: '  ' });
		await flush();
		expect(listDocuments).toHaveBeenCalledOnce();
	});

	it('appends the next page at the offset of what it holds', async () => {
		vi.mocked(listDocuments).mockResolvedValueOnce(page([3, 2], 3));
		const store = new DocumentsStore(new LookupsStore());
		store.applyFilter(emptyDocumentFilter());
		await flush();

		vi.mocked(listDocuments).mockResolvedValueOnce(page([1], 3));
		await store.loadMore();

		expect(vi.mocked(listDocuments).mock.calls[1][1]).toMatchObject({ offset: 2 });
		expect(store.documents.map((d) => d.id)).toEqual([3, 2, 1]);
	});

	it('keeps the rows and says why when more cannot be loaded', async () => {
		vi.mocked(listDocuments).mockResolvedValueOnce(page([2], 2));
		const store = new DocumentsStore(new LookupsStore());
		store.applyFilter(emptyDocumentFilter());
		await flush();

		vi.mocked(listDocuments).mockRejectedValueOnce(new ApiError(500, 'internal_error', 'x'));
		await store.loadMore();

		expect(store.documents).toHaveLength(1);
		expect(store.moreError?.code).toBe('internal_error');
	});

	it('shows the error of a failed first page, and reload tries again', async () => {
		vi.mocked(listDocuments).mockRejectedValueOnce(new Error('offline'));
		const store = new DocumentsStore(new LookupsStore());
		store.applyFilter(emptyDocumentFilter());
		await flush();
		expect(store.status).toBe('error');
		expect(store.error?.code).toBe('network_error');

		vi.mocked(listDocuments).mockResolvedValueOnce(page([1], 1));
		await store.reload();
		expect(store.status).toBe('ready');
	});

	it('ignores the answer of a superseded fetch', async () => {
		let resolveFirst!: (value: ReturnType<typeof page>) => void;
		vi.mocked(listDocuments).mockImplementationOnce(
			() => new Promise((resolve) => (resolveFirst = resolve))
		);
		vi.mocked(listDocuments).mockResolvedValueOnce(page([9], 1));
		const store = new DocumentsStore(new LookupsStore());
		store.applyFilter(emptyDocumentFilter());
		await flush(); // the first request is out
		store.applyFilter({ ...emptyDocumentFilter(), q: 'x' });
		await flush();
		resolveFirst(page([1], 1));
		await flush();
		expect(store.documents.map((d) => d.id)).toEqual([9]);
	});

	it('offers the providers of the registered importers, and those already chosen', async () => {
		const { listDocumentProviders } = await import('#lib/api/index.js');
		vi.mocked(listDocumentProviders).mockResolvedValue(['paypal', 'amazon']);
		vi.mocked(listDocuments).mockResolvedValue(page([], 0));
		const store = new DocumentsStore(new LookupsStore(), new DocumentProvidersStore());
		expect(store.providers).toEqual([]);
		await store.loadProviders();
		store.applyFilter({ ...emptyDocumentFilter(), provider: ['zalando', 'amazon'] });
		expect(store.providers).toEqual(['amazon', 'paypal', 'zalando']);
	});

	it('offers a provider once whatever its case, keeping the first spelling', async () => {
		const { listDocumentProviders } = await import('#lib/api/index.js');
		vi.mocked(listDocumentProviders).mockResolvedValue(['amazon', 'paypal']);
		vi.mocked(listDocuments).mockResolvedValue(page([], 0));
		const store = new DocumentsStore(new LookupsStore(), new DocumentProvidersStore());
		await store.loadProviders();
		store.applyFilter({ ...emptyDocumentFilter(), provider: ['Amazon'] });
		expect(store.providers).toEqual(['amazon', 'paypal']);
	});
});

describe('DocumentDetailStore', () => {
	it('loads one document', async () => {
		vi.mocked(getDocument).mockResolvedValue(documentDetail({ id: 5 }));
		const store = new DocumentDetailStore(new LookupsStore());
		const loading = store.load(5);
		expect(store.status).toBe('loading');
		await loading;
		expect(store.status).toBe('ready');
		expect(store.document?.id).toBe(5);
	});

	it('reports a missing document', async () => {
		vi.mocked(getDocument).mockRejectedValue(new ApiError(404, 'not_found', 'gone'));
		const store = new DocumentDetailStore(new LookupsStore());
		await store.load(5);
		expect(store.status).toBe('error');
		expect(store.error?.code).toBe('not_found');
	});
});
