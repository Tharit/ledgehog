import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './http.js';
import { getNewUnitCount, getQueue, getUnit } from './units.js';

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

describe('getNewUnitCount', () => {
	it('sends the snapshot', async () => {
		await getNewUnitCount('snap 1');
		expect(lastUrl()).toBe('/api/units/queue/new-count?since=snap+1');
	});
});
