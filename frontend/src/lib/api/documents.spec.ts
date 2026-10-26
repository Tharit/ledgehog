import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { documentQuery, getDocument, listDocumentProviders, listDocuments } from './documents.js';
import type { DocumentFilter } from './types.js';

const fetchMock = vi.fn();

function reply(payload: unknown): Response {
	return new Response(JSON.stringify(payload), {
		status: 200,
		headers: { 'Content-Type': 'application/json' }
	});
}

function lastUrl(): string {
	return (fetchMock.mock.calls.at(-1) as [string])[0];
}

const empty: DocumentFilter = { provider: [], q: '' };

beforeEach(() => {
	fetchMock.mockReset();
	fetchMock.mockImplementation(async () =>
		reply({ documents: [], total: 0, limit: 100, offset: 0 })
	);
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe('listDocuments', () => {
	it('asks for the first page of an empty filter with just the limit', async () => {
		await listDocuments(empty);
		expect(lastUrl()).toBe('/api/documents?limit=100');
	});

	it('sends the offset past the first page and the limit it was given', async () => {
		await listDocuments(empty, { limit: 50, offset: 100 });
		expect(lastUrl()).toBe('/api/documents?limit=50&offset=100');
	});

	it('repeats provider, keeps the API names', async () => {
		await listDocuments({
			provider: ['amazon', 'paypal'],
			from: '2026-10-01',
			to: '2026-10-31',
			amount_min: 100,
			amount_max: 5000,
			currency: 'EUR',
			q: ' rewe '
		});
		const url = new URL(lastUrl(), 'http://x');
		expect(url.searchParams.getAll('provider')).toEqual(['amazon', 'paypal']);
		expect(url.searchParams.get('from')).toBe('2026-10-01');
		expect(url.searchParams.get('to')).toBe('2026-10-31');
		expect(url.searchParams.get('amount_min')).toBe('100');
		expect(url.searchParams.get('amount_max')).toBe('5000');
		expect(url.searchParams.get('currency')).toBe('EUR');
		expect(url.searchParams.get('q')).toBe('rewe');
	});

	it('leaves out a blank text', () => {
		expect(documentQuery({ ...empty, q: '  ' }).q).toBeUndefined();
	});
});

describe('getDocument', () => {
	it('reads one document by id', async () => {
		fetchMock.mockImplementation(async () => reply({ id: 7 }));
		await expect(getDocument(7)).resolves.toEqual({ id: 7 });
		expect(lastUrl()).toBe('/api/documents/7');
	});
});

describe('listDocumentProviders', () => {
	it('returns the providers the server lists', async () => {
		fetchMock.mockImplementation(async () => reply({ providers: ['amazon', 'paypal'] }));
		expect(await listDocumentProviders()).toEqual(['amazon', 'paypal']);
		expect(lastUrl()).toBe('/api/documents/providers');
	});
});
