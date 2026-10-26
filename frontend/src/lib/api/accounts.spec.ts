import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createAccount, listAccounts } from './accounts.js';
import { ApiError } from './http.js';

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

describe('listAccounts', () => {
	it('reads the accounts list', async () => {
		fetchMock.mockResolvedValue(reply({ accounts: [{ id: 1 }] }));

		expect(await listAccounts()).toEqual([{ id: 1 }]);
		expect(last()[0]).toBe('/api/ledger/accounts');
	});
});

describe('createAccount', () => {
	it('posts the body and returns the account with the settle result', async () => {
		const answer = { account: { id: 8, name: 'Cash USD' }, settle: { error: null } };
		fetchMock.mockResolvedValue(reply(answer, 201));

		const out = await createAccount({
			name: 'Cash USD',
			kind: 'cash',
			currency: 'USD',
			providers: [],
			sort_order: 0
		});

		const [url, init] = last();
		expect(url).toBe('/api/ledger/accounts');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual({
			name: 'Cash USD',
			kind: 'cash',
			currency: 'USD',
			providers: [],
			sort_order: 0
		});
		expect(out).toEqual(answer);
	});

	it('sends the optional fields when given', async () => {
		fetchMock.mockResolvedValue(reply({ account: { id: 9 }, settle: {} }, 201));

		await createAccount({
			name: 'Visa',
			kind: 'card',
			currency: 'EUR',
			sort_order: 3,
			providers: [],
			external_ref: 'DE00',
			note: 'n',
			icon: 'credit-card',
			color: 'plum'
		});

		expect(JSON.parse(last()[1].body as string)).toMatchObject({
			external_ref: 'DE00',
			note: 'n',
			icon: 'credit-card',
			color: 'plum',
			sort_order: 3
		});
	});

	it('refuses a taken external reference with 409 conflict and its reason', async () => {
		fetchMock.mockResolvedValue(failure(409, 'conflict', { reason: 'duplicate_external_ref' }));

		await expect(
			createAccount({
				name: 'A',
				kind: 'checking',
				currency: 'EUR',
				sort_order: 0,
				providers: [],
				external_ref: 'X'
			})
		).rejects.toMatchObject({
			status: 409,
			code: 'conflict',
			details: { reason: 'duplicate_external_ref' }
		});
	});

	it('refuses an unknown currency with 422 validation_error', async () => {
		fetchMock.mockResolvedValue(failure(422, 'validation_error', { reason: 'unknown_currency' }));

		const error = await createAccount({
			name: 'A',
			kind: 'cash',
			currency: 'ZZZ',
			providers: [],
			sort_order: 0
		}).catch((e: unknown) => e);

		expect(error).toBeInstanceOf(ApiError);
		expect(error).toMatchObject({ status: 422, code: 'validation_error' });
	});
});
