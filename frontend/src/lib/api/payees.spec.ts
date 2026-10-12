import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPayee, deletePayee, mergePayee, updatePayee } from './payees.js';

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

describe('createPayee and updatePayee', () => {
	it('posts name and note', async () => {
		fetchMock.mockResolvedValue(reply({ payee: { id: 1 }, settle: {} }, 201));

		await createPayee({ name: 'REWE', note: 'groceries' });

		const [url, init] = last();
		expect(url).toBe('/api/ledger/payees');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual({ name: 'REWE', note: 'groceries' });
	});

	it('puts only what changed', async () => {
		fetchMock.mockResolvedValue(reply({ payee: { id: 3 }, settle: {} }));

		await updatePayee(3, { color: null });

		const [url, init] = last();
		expect(url).toBe('/api/ledger/payees/3');
		expect(init.method).toBe('PUT');
		expect(JSON.parse(init.body as string)).toEqual({ color: null });
	});

	it('reports a taken name', async () => {
		fetchMock.mockResolvedValue(failure(409, 'conflict', { reason: 'duplicate_name' }));

		await expect(createPayee({ name: 'REWE' })).rejects.toMatchObject({
			code: 'conflict',
			details: { reason: 'duplicate_name' }
		});
	});
});

describe('deletePayee', () => {
	it('previews with dry_run', async () => {
		fetchMock.mockResolvedValue(reply({ deletable: true, rules: [] }));

		await deletePayee(3, { dryRun: true });

		const [url, init] = last();
		expect(url).toBe('/api/ledger/payees/3?dry_run=true');
		expect(init.method).toBe('DELETE');
	});

	it('reports the entries that hold a payee', async () => {
		fetchMock.mockResolvedValue(
			failure(409, 'conflict', { reason: 'payee_in_use', held: { entries: 12 } })
		);

		const error = await deletePayee(3).catch((e) => e);

		expect(error.details).toEqual({ reason: 'payee_in_use', held: { entries: 12 } });
	});
});

describe('mergePayee', () => {
	it('previews, then sends the previewed count with the real run', async () => {
		fetchMock.mockImplementation(() => Promise.resolve(reply({ entry_count: 5 })));

		await mergePayee(3, 8, { dryRun: true });
		expect(JSON.parse(last()[1].body as string)).toEqual({
			into: 8,
			dry_run: true,
			expected_count: null
		});

		await mergePayee(3, 8, { expectedCount: 5 });
		const [url, init] = last();
		expect(url).toBe('/api/ledger/payees/3/merge');
		expect(JSON.parse(init.body as string)).toEqual({
			into: 8,
			dry_run: false,
			expected_count: 5
		});
	});

	it('reports a moved count', async () => {
		fetchMock.mockResolvedValue(
			failure(409, 'conflict', { reason: 'filter_result_changed', expected: 5, actual: 6 })
		);

		await expect(mergePayee(3, 8, { expectedCount: 5 })).rejects.toMatchObject({
			details: { expected: 5, actual: 6 }
		});
	});
});
