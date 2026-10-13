import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './http.js';
import { createSource, deleteSource, updateSource } from './sources.js';

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
	fetchMock.mockImplementation(async () => reply({}));
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('createSource', () => {
	it('posts the client id, account, signed amount, date and purpose', async () => {
		await createSource({
			id: 'abc-123',
			account_id: 4,
			amount: -1250,
			booked_on: '2026-10-13',
			purpose: 'groceries'
		});

		const [url, init] = last();
		expect(url).toBe('/api/ledger/sources');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual({
			id: 'abc-123',
			account_id: 4,
			amount: -1250,
			booked_on: '2026-10-13',
			purpose: 'groceries'
		});
	});

	it.each([
		[422, 'account_synced', null],
		[409, 'stale_reference', { field: 'account_id' }],
		[409, 'conflict', { reason: 'id_taken' }],
		[422, 'validation_error', [{ location: ['body', 'amount'], message: 'm', type: 't' }]]
	])('answers %s %s with its code and details', async (status, code, details) => {
		fetchMock.mockImplementation(async () => failure(status, code, details));

		const error = await createSource({
			id: 'a',
			account_id: 1,
			amount: 1,
			booked_on: '2026-10-13'
		}).catch((e) => e);

		expect(error).toBeInstanceOf(ApiError);
		expect(error).toMatchObject({ status, code, details });
	});
});

describe('updateSource', () => {
	it('puts only the changes, with the dry-run flag and the versions as strings of an object', async () => {
		await updateSource(7, { amount: -500 }, { dryRun: true, versions: { 11: 2, 12: 5 } });

		const [url, init] = last();
		expect(url).toBe('/api/ledger/sources/7');
		expect(init.method).toBe('PUT');
		expect(JSON.parse(init.body as string)).toEqual({
			amount: -500,
			dry_run: true,
			expected_versions: { '11': 2, '12': 5 }
		});
	});

	it('is a real run by default and can clear the purpose with null', async () => {
		await updateSource(7, { purpose: null });

		expect(JSON.parse(last()[1].body as string)).toEqual({
			purpose: null,
			dry_run: false,
			expected_versions: {}
		});
	});

	it('answers a version conflict with the entries that moved', async () => {
		fetchMock.mockImplementation(async () => failure(409, 'conflict', { entry_ids: [11] }));

		await expect(updateSource(7, { amount: 1 })).rejects.toMatchObject({
			status: 409,
			code: 'conflict',
			details: { entry_ids: [11] }
		});
	});

	it.each([
		[404, 'not_found'],
		[422, 'not_user_authored'],
		[409, 'try_again']
	])('answers %s %s', async (status, code) => {
		fetchMock.mockImplementation(async () => failure(status, code));

		await expect(updateSource(7, { amount: 1 })).rejects.toMatchObject({ status, code });
	});
});

describe('deleteSource', () => {
	it('deletes with the dry-run flag and each version as a repeated entry:version', async () => {
		await deleteSource(7, { dryRun: true, versions: { 11: 2, 12: 5 } });

		const [url, init] = last();
		expect(init.method).toBe('DELETE');
		const query = new URL(url, 'http://x').searchParams;
		expect(new URL(url, 'http://x').pathname).toBe('/api/ledger/sources/7');
		expect(query.get('dry_run')).toBe('true');
		expect(query.getAll('expected_versions')).toEqual(['11:2', '12:5']);
	});

	it('sends no versions when it has none', async () => {
		await deleteSource(7);

		const query = new URL(last()[0], 'http://x').searchParams;
		expect(query.get('dry_run')).toBe('false');
		expect(query.has('expected_versions')).toBe(false);
	});
});
