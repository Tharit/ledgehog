import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createCategory, deleteCategory, mergeCategory, updateCategory } from './categories.js';

const fetchMock = vi.fn();

function reply(payload: unknown, status = 200): Response {
	return new Response(JSON.stringify(payload), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

function failure(status: number, code: string, details: unknown = null): Response {
	return reply({ error: { code, message: 'x', details } }, status);
}

function last(): [string, RequestInit] {
	return fetchMock.mock.calls.at(-1) as [string, RequestInit];
}

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('createCategory and updateCategory', () => {
	it('posts the body as given', async () => {
		fetchMock.mockResolvedValue(reply({ category: { id: 1 }, settle: {} }, 201));

		await createCategory({ name: 'Food', kind: 'expense', sort_order: 0 });

		const [url, init] = last();
		expect(url).toBe('/api/ledger/categories');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual({
			name: 'Food',
			kind: 'expense',
			sort_order: 0
		});
	});

	it('puts only the fields it is given; null clears', async () => {
		fetchMock.mockResolvedValue(reply({ category: { id: 4 }, settle: {} }));

		await updateCategory(4, { icon: null, color: 'sage' });

		const [url, init] = last();
		expect(url).toBe('/api/ledger/categories/4');
		expect(init.method).toBe('PUT');
		expect(JSON.parse(init.body as string)).toEqual({ icon: null, color: 'sage' });
	});

	it('reports a taken name as a conflict with its reason', async () => {
		fetchMock.mockResolvedValue(failure(409, 'conflict', { reason: 'duplicate_name' }));

		await expect(createCategory({ name: 'Food', sort_order: 0 })).rejects.toMatchObject({
			status: 409,
			code: 'conflict',
			details: { reason: 'duplicate_name' }
		});
	});

	it('reports a validation error by its code', async () => {
		fetchMock.mockResolvedValue(failure(422, 'validation_error', []));

		await expect(updateCategory(4, { name: '' })).rejects.toMatchObject({
			status: 422,
			code: 'validation_error'
		});
	});
});

describe('deleteCategory', () => {
	it('sends dry_run as a query parameter', async () => {
		fetchMock.mockResolvedValue(reply({ deletable: true }));

		await deleteCategory(4, { dryRun: true });

		const [url, init] = last();
		expect(url).toBe('/api/ledger/categories/4?dry_run=true');
		expect(init.method).toBe('DELETE');
	});

	it('is a real run by default', async () => {
		fetchMock.mockResolvedValue(reply({ deleted: true }));

		await deleteCategory(4);

		expect(last()[0]).toBe('/api/ledger/categories/4?dry_run=false');
	});

	it('reports what holds a category', async () => {
		const held = { entries: 3, rules: 1, children: 0 };
		fetchMock.mockResolvedValue(failure(409, 'conflict', { reason: 'category_in_use', held }));

		const error = await deleteCategory(4).catch((e) => e);

		expect(error.details).toEqual({ reason: 'category_in_use', held });
	});
});

describe('mergeCategory', () => {
	it('previews with dry_run and no count', async () => {
		fetchMock.mockResolvedValue(reply({ entry_count: 7 }));

		const out = await mergeCategory(4, 9, { dryRun: true });

		expect(out).toEqual({ entry_count: 7 });
		const [url, init] = last();
		expect(url).toBe('/api/ledger/categories/4/merge');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual({
			into: 9,
			dry_run: true,
			expected_count: null
		});
	});

	it('sends the previewed count with the real run', async () => {
		fetchMock.mockResolvedValue(reply({ entry_count: 7 }));

		await mergeCategory(4, 9, { expectedCount: 7 });

		expect(JSON.parse(last()[1].body as string)).toEqual({
			into: 9,
			dry_run: false,
			expected_count: 7
		});
	});

	it('reports a moved count with what it was and is', async () => {
		fetchMock.mockResolvedValue(
			failure(409, 'conflict', { reason: 'filter_result_changed', expected: 7, actual: 8 })
		);

		const error = await mergeCategory(4, 9, { expectedCount: 7 }).catch((e) => e);

		expect(error.details).toEqual({ reason: 'filter_result_changed', expected: 7, actual: 8 });
	});

	it('reports a vanished target as a stale reference naming the field', async () => {
		fetchMock.mockResolvedValue(
			failure(409, 'stale_reference', { field: 'into', entity: 'category', id: 9 })
		);

		await expect(mergeCategory(4, 9, { dryRun: true })).rejects.toMatchObject({
			status: 409,
			code: 'stale_reference',
			details: { field: 'into' }
		});
	});
});
