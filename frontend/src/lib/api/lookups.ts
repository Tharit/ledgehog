// The lists the ledger resolves ids against (names, icons, colours): small, loaded once.
import { request } from './http.js';
import type { Category, Payee, Tag } from './types.js';

export async function listCategories(signal?: AbortSignal): Promise<Category[]> {
	const { categories } = await request<{ categories: Category[] }>(
		'GET',
		'/api/ledger/categories',
		{
			signal
		}
	);
	return categories;
}

export async function listPayees(signal?: AbortSignal): Promise<Payee[]> {
	const { payees } = await request<{ payees: Payee[] }>('GET', '/api/ledger/payees', { signal });
	return payees;
}

export async function listTags(signal?: AbortSignal): Promise<Tag[]> {
	const { tags } = await request<{ tags: Tag[] }>('GET', '/api/ledger/tags', { signal });
	return tags;
}
