import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './http.js';
import { commitUnit, getQueue, getQueueCount, getUnit, previewUnit } from './units.js';

const fetchMock = vi.fn();

function reply(payload: unknown, status = 200): Response {
	return new Response(JSON.stringify(payload), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

function lastUrl(): string {
	return (fetchMock.mock.calls.at(-1) as [string])[0];
}

beforeEach(() => {
	fetchMock.mockReset();
	fetchMock.mockImplementation(async () => reply({}));
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('getUnit', () => {
	it('asks for the unit of an entry', async () => {
		await getUnit(42);
		expect(lastUrl()).toBe('/api/units/42');
	});

	it('answers a missing unit with its code', async () => {
		fetchMock.mockImplementation(async () =>
			reply({ error: { code: 'not_found', message: 'x', details: null } }, 404)
		);
		await expect(getUnit(7)).rejects.toMatchObject({ code: 'not_found', status: 404 });
		await expect(getUnit(7)).rejects.toBeInstanceOf(ApiError);
	});
});

describe('getQueue', () => {
	it('asks for the first page of every section with the default limit', async () => {
		await getQueue();
		expect(lastUrl()).toBe('/api/units/queue?limit=50');
	});

	it('continues one section after a cursor', async () => {
		await getQueue({ section: 'waiting', cursor: 'abc', limit: 20 });
		expect(lastUrl()).toBe('/api/units/queue?limit=20&section=waiting&cursor=abc');
	});
});

describe('getQueueCount', () => {
	it('reads the count of the units that can be acted on', async () => {
		fetchMock.mockImplementation(async () => reply({ count: 7 }));
		expect(await getQueueCount()).toBe(7);
		expect(lastUrl()).toBe('/api/units/queue/count');
	});
});

describe('previewUnit and commitUnit', () => {
	const draft = { anchor_entry_id: 5, entries: [], removed_entry_ids: [], reresolve_all: false };

	it('post the draft as JSON to the preview', async () => {
		await previewUnit(draft);
		const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
		expect(url).toBe('/api/units/preview');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual(draft);
	});

	it('post it to the commit', async () => {
		await commitUnit(draft);
		const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
		expect(url).toBe('/api/units/commit');
		expect(init.method).toBe('POST');
	});

	it('answer a conflict with its code and the entries that moved', async () => {
		fetchMock.mockImplementation(async () =>
			reply({ error: { code: 'conflict', message: 'x', details: { entry_ids: [5] } } }, 409)
		);
		await expect(commitUnit(draft)).rejects.toMatchObject({
			code: 'conflict',
			details: { entry_ids: [5] }
		});
	});
});
