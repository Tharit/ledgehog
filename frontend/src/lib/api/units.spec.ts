import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './http.js';
import { commitUnit, getQueue, getQueueCounts, getUnit, previewUnit } from './units.js';

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
		expect(lastUrl()).toBe('/api/units/queue?limit=50&cut=date');
	});

	it('sends the cut it is given, date explicitly', async () => {
		await getQueue({ cut: 'counterparty' });
		expect(lastUrl()).toBe('/api/units/queue?limit=50&cut=counterparty');
		await getQueue({ cut: 'date' });
		expect(lastUrl()).toBe('/api/units/queue?limit=50&cut=date');
	});

	it('continues one section after a cursor', async () => {
		await getQueue({ section: 'waiting', cursor: 'abc', limit: 20 });
		expect(lastUrl()).toBe('/api/units/queue?limit=20&section=waiting&cursor=abc&cut=date');
	});
});

describe('getQueue with an account filter', () => {
	it('repeats account_id, and sends none for the whole queue', async () => {
		await getQueue({ accountIds: [3, 5] });
		expect(lastUrl()).toBe('/api/units/queue?limit=50&account_id=3&account_id=5&cut=date');
		await getQueue({ accountIds: [] });
		expect(lastUrl()).toBe('/api/units/queue?limit=50&cut=date');
	});
});

describe('getQueueCounts', () => {
	it('reads the count of the units that can be acted on, with its split', async () => {
		fetchMock.mockImplementation(async () =>
			reply({ count: 7, pending_review: 5, needs_account: 2 })
		);
		expect(await getQueueCounts()).toEqual({ count: 7, pending_review: 5, needs_account: 2 });
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
