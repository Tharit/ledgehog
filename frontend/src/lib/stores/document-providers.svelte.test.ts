import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, listDocumentProviders } from '#lib/api/index.js';
import { DocumentProvidersStore } from './document-providers.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listDocumentProviders: vi.fn()
}));

beforeEach(() => vi.resetAllMocks());

describe('DocumentProvidersStore', () => {
	it('is empty until loaded, then holds the list', async () => {
		vi.mocked(listDocumentProviders).mockResolvedValue(['amazon', 'paypal']);
		const store = new DocumentProvidersStore();
		expect(store.providers).toEqual([]);
		expect(store.loaded).toBe(false);
		await store.load();
		expect(store.providers).toEqual(['amazon', 'paypal']);
		expect(store.loaded).toBe(true);
	});

	it('keeps the list held when a fetch fails', async () => {
		vi.mocked(listDocumentProviders).mockResolvedValueOnce(['amazon']);
		const store = new DocumentProvidersStore();
		await store.load();
		vi.mocked(listDocumentProviders).mockRejectedValueOnce(
			new ApiError(0, 'network_error', 'down')
		);
		await store.load();
		expect(store.providers).toEqual(['amazon']);
	});
});
