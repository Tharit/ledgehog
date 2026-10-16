// Documents (spec §5.8): browsed here, never written; a link is made by a unit's commit.
import { request, type Query } from './http.js';
import type { DocumentDetail, DocumentFilter, DocumentPage, DocumentProviders } from './types.js';

export const DOCUMENT_PAGE_SIZE = 100;

/**
 * A filter as query parameters, in the API's names and a fixed order (the same filter is always
 * the same string). Empty values are left out and `provider` is a repeated parameter.
 */
export function documentQuery(filter: DocumentFilter): Query {
	const text = filter.q.trim();
	return {
		provider: filter.provider,
		from: filter.from,
		to: filter.to,
		amount_min: filter.amount_min,
		amount_max: filter.amount_max,
		currency: filter.currency,
		q: text === '' ? undefined : text,
		linked: filter.linked
	};
}

export type DocumentPageOptions = { limit?: number; offset?: number; signal?: AbortSignal };

/** One page of documents matching `filter`, newest first; `total` counts every match. */
export function listDocuments(
	filter: DocumentFilter,
	{ limit = DOCUMENT_PAGE_SIZE, offset = 0, signal }: DocumentPageOptions = {}
): Promise<DocumentPage> {
	return request('GET', '/api/documents', {
		query: { ...documentQuery(filter), limit, offset: offset > 0 ? offset : undefined },
		signal
	});
}

/** The providers of the registered document importers, sorted: what a payee can name. */
export async function listDocumentProviders(signal?: AbortSignal): Promise<string[]> {
	const out = await request<DocumentProviders>('GET', '/api/documents/providers', { signal });
	return out.providers;
}

/** One document with its lines and, when no entry carries it, the transactions it would match. */
export function getDocument(id: number, signal?: AbortSignal): Promise<DocumentDetail> {
	return request('GET', `/api/documents/${id}`, { signal });
}
