import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, request, setChangesListener, setUnauthenticatedHandler } from './http.js';
import { login, logout, me } from './session.js';
import { listAccounts } from './accounts.js';
import { readChanges } from './changes.js';
import { getConfig } from './config.js';

const fetchMock = vi.fn();

// a Response body can be read once, so every call gets a fresh one
function answer(make: () => Response): void {
	fetchMock.mockImplementation(async () => make());
}

function reply(status: number, payload?: unknown): Response {
	return new Response(payload === undefined ? null : JSON.stringify(payload), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

function failure(status: number, code: string, message = code, details: unknown = null): Response {
	return reply(status, { error: { code, message, details } });
}

function lastCall(): { url: string; init: RequestInit } {
	const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
	return { url, init };
}

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	setUnauthenticatedHandler(null);
	vi.unstubAllGlobals();
});

describe('the change values of a write', () => {
	const values = { ledger: 'b:3', documents: 'b:1', accounts: { '7': 'b:2' } };
	const withHeader = (status = 200) =>
		new Response('{}', {
			status,
			headers: { 'Content-Type': 'application/json', 'X-Ledger-Changes': JSON.stringify(values) }
		});

	afterEach(() => setChangesListener(null));

	it('go to the listener after every answer that is not a read, an error answer included', async () => {
		const listener = vi.fn();
		setChangesListener(listener);

		answer(() => withHeader());
		await request('POST', '/api/x', { body: {} });
		expect(listener).toHaveBeenCalledWith(values);

		answer(() => withHeader(409));
		await expect(request('DELETE', '/api/x')).rejects.toBeInstanceOf(ApiError);
		expect(listener).toHaveBeenCalledTimes(2);
	});

	it('are not taken from a read, nor from an answer without the header or with a broken one', async () => {
		const listener = vi.fn();
		setChangesListener(listener);

		answer(() => withHeader());
		await request('GET', '/api/x');
		answer(() => reply(200, {}));
		await request('POST', '/api/x');
		answer(() => new Response('{}', { status: 200, headers: { 'X-Ledger-Changes': 'not json' } }));
		await request('POST', '/api/x');

		expect(listener).not.toHaveBeenCalled();
	});
});

describe('request', () => {
	it('sends the cookie same-origin and returns parsed JSON', async () => {
		answer(() => reply(200, { ok: 1 }));
		await expect(request('GET', '/api/x')).resolves.toEqual({ ok: 1 });
		const { url, init } = lastCall();
		expect(url).toBe('/api/x');
		expect(init.method).toBe('GET');
		expect(init.credentials).toBe('same-origin');
		expect(init.body).toBeUndefined();
	});

	it('sends a JSON body with its content type', async () => {
		answer(() => reply(200, {}));
		await request('POST', '/api/x', { body: { a: 1 } });
		const { init } = lastCall();
		expect(init.body).toBe('{"a":1}');
		expect(init.headers).toMatchObject({ 'Content-Type': 'application/json' });
	});

	it('sends a FormData body as it is, without a content type of its own', async () => {
		answer(() => reply(200, {}));
		const form = new FormData();
		form.append('dry_run', 'true');
		await request('POST', '/api/x', { body: form });
		const { init } = lastCall();
		expect(init.body).toBe(form);
		expect(init.headers).not.toHaveProperty('Content-Type');
	});

	it('answers undefined for 204', async () => {
		answer(() => new Response(null, { status: 204 }));
		await expect(request('DELETE', '/api/x')).resolves.toBeUndefined();
	});

	it('builds the query: skips empty values, repeats arrays, encodes', async () => {
		answer(() => reply(200, {}));
		await request('GET', '/api/x', {
			query: { q: 'a b&c', n: 0, flag: false, none: null, gone: undefined, tag: [1, 2] }
		});
		expect(lastCall().url).toBe('/api/x?q=a+b%26c&n=0&flag=false&tag=1&tag=2');
		await request('GET', '/api/x', { query: { a: undefined } });
		expect(lastCall().url).toBe('/api/x');
	});

	it('passes the abort signal on', async () => {
		answer(() => reply(200, {}));
		const controller = new AbortController();
		await request('GET', '/api/x', { signal: controller.signal });
		expect(lastCall().init.signal).toBe(controller.signal);
	});

	it('maps the error envelope to an ApiError', async () => {
		answer(() => failure(409, 'conflict', 'Someone changed this.', { reason: 'x' }));
		const error = await request('POST', '/api/x').catch((e) => e);
		expect(error).toBeInstanceOf(ApiError);
		expect(error).toMatchObject({
			status: 409,
			code: 'conflict',
			message: 'Someone changed this.',
			details: { reason: 'x' }
		});
	});

	it('answers http_error for a non-JSON error body', async () => {
		answer(() => new Response('<html>bad gateway</html>', { status: 502 }));
		const error = await request('GET', '/api/x').catch((e) => e);
		expect(error).toMatchObject({ status: 502, code: 'http_error' });
	});

	it('answers network_error when the server cannot be reached', async () => {
		fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
		const error = await request('GET', '/api/x').catch((e) => e);
		expect(error).toBeInstanceOf(ApiError);
		expect(error).toMatchObject({ status: 0, code: 'network_error' });
	});

	it('answers network_error for a success body that is not JSON', async () => {
		answer(() => new Response('<html></html>', { status: 200 }));
		await expect(request('GET', '/api/x')).rejects.toMatchObject({ code: 'network_error' });
	});

	it('lets an abort through unchanged', async () => {
		const controller = new AbortController();
		controller.abort();
		const abort = new DOMException('aborted', 'AbortError');
		fetchMock.mockRejectedValue(abort);
		await expect(request('GET', '/api/x', { signal: controller.signal })).rejects.toBe(abort);
	});

	it('calls the hook for an unauthenticated answer, and still rejects', async () => {
		const hook = vi.fn();
		setUnauthenticatedHandler(hook);
		answer(() => failure(401, 'unauthenticated'));
		await expect(request('GET', '/api/x')).rejects.toMatchObject({ code: 'unauthenticated' });
		expect(hook).toHaveBeenCalledOnce();
	});

	it('does not call the hook for other 401 codes such as invalid_credentials', async () => {
		const hook = vi.fn();
		setUnauthenticatedHandler(hook);
		answer(() => failure(401, 'invalid_credentials'));
		await expect(request('POST', '/api/session')).rejects.toMatchObject({
			code: 'invalid_credentials'
		});
		expect(hook).not.toHaveBeenCalled();
	});
});

describe('the endpoint modules', () => {
	it('session: login, me and logout use /api/session', async () => {
		const user = { id: 1, login: 'ada', display_name: 'Ada' };
		answer(() => reply(200, user));
		await expect(login('ada', 'pw')).resolves.toEqual(user);
		expect(lastCall().init.method).toBe('POST');
		expect(lastCall().url).toBe('/api/session');
		expect(lastCall().init.body).toBe('{"login":"ada","password":"pw"}');

		await expect(me()).resolves.toEqual(user);
		expect(lastCall().init.method).toBe('GET');

		answer(() => new Response(null, { status: 204 }));
		await expect(logout()).resolves.toBeUndefined();
		expect(lastCall().init.method).toBe('DELETE');
	});

	it('config: reads /api/config', async () => {
		const config = { base_currency: 'EUR', timezone: 'Europe/Berlin', locale: 'de' };
		answer(() => reply(200, config));
		await expect(getConfig()).resolves.toEqual(config);
		expect(lastCall().url).toBe('/api/config');
	});

	it('changes: reads /api/changes', async () => {
		const read = { ledger: 'b:1', documents: 'b:1', accounts: {}, active_task: null };
		answer(() => reply(200, read));
		await expect(readChanges()).resolves.toEqual(read);
		expect(lastCall().url).toBe('/api/changes');
	});

	it('accounts: unwraps the list', async () => {
		answer(() => reply(200, { accounts: [{ id: 1, name: 'Giro' }] }));
		await expect(listAccounts()).resolves.toEqual([{ id: 1, name: 'Giro' }]);
		expect(lastCall().url).toBe('/api/ledger/accounts');
	});
});
