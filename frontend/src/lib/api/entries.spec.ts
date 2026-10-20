import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { exportUrl, filterQuery, getEntry, listEntries } from './entries.js';
import { listCategories, listPayees, listTags } from './lookups.js';
import type { EntryFilter } from './types.js';

const fetchMock = vi.fn();

function reply(payload: unknown): Response {
	return new Response(JSON.stringify(payload), {
		status: 200,
		headers: { 'Content-Type': 'application/json' }
	});
}

function lastUrl(): string {
	return (fetchMock.mock.calls.at(-1) as [string])[0];
}

const empty: EntryFilter = {
	account_id: [],
	category_id: [],
	category_descendants: true,
	uncategorised: false,
	payee_id: [],
	tag_id: [],
	q: '',
	type: [],
	flag: []
};

beforeEach(() => {
	fetchMock.mockReset();
	fetchMock.mockImplementation(async () => reply({ entries: [], total: 0, limit: 100, offset: 0 }));
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('exportUrl', () => {
	it('is the export route with nothing for an empty filter, and never fetches', () => {
		expect(exportUrl(empty)).toBe('/api/ledger/entries/export');
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it('carries the list filter in the same parameters and order, without a page', () => {
		const filter: EntryFilter = {
			...empty,
			from: '2026-10-01',
			account_id: [2, 1],
			flag: ['waiting'],
			q: ' bakery ',
			uncategorised: true
		};
		const query = exportUrl(filter).split('?')[1];
		expect(exportUrl(filter)).toMatch(/^\/api\/ledger\/entries\/export\?/);
		expect(query).toBe(
			'from=2026-10-01&account_id=2&account_id=1&uncategorised=true&q=bakery&flag=waiting'
		);
		expect(query).not.toMatch(/limit|offset/);
	});
});

describe('listEntries', () => {
	it('asks for the first page of an empty filter with just the limit', async () => {
		await listEntries(empty);
		expect(lastUrl()).toBe('/api/ledger/entries?limit=100');
	});

	it('sends the offset once it is past the first page, and the limit it was given', async () => {
		await listEntries(empty, { limit: 50, offset: 100 });
		expect(lastUrl()).toBe('/api/ledger/entries?limit=50&offset=100');
	});

	it('repeats array parameters and keeps the API names', async () => {
		await listEntries({
			...empty,
			from: '2026-10-01',
			to: '2026-10-31',
			account_id: [2, 1],
			tag_id: [7],
			flag: ['unconfirmed', 'waiting'],
			type: ['flow']
		});
		expect(lastUrl()).toBe(
			'/api/ledger/entries?from=2026-10-01&to=2026-10-31&account_id=2&account_id=1&tag_id=7' +
				'&type=flow&flag=unconfirmed&flag=waiting&limit=100'
		);
	});

	it('sends the amount range with its currency and direction', async () => {
		await listEntries({
			...empty,
			amount_min: 500,
			amount_max: 2000,
			currency: 'EUR',
			direction: 'out'
		});
		expect(lastUrl()).toBe(
			'/api/ledger/entries?amount_min=500&amount_max=2000&currency=EUR&direction=out&limit=100'
		);
	});

	it('sends a zero amount bound (zero is a value, not an absent one)', async () => {
		await listEntries({ ...empty, amount_min: 0, currency: 'EUR' });
		expect(lastUrl()).toContain('amount_min=0');
	});

	it('trims the text and leaves a blank one out', async () => {
		await listEntries({ ...empty, q: '  rewe  ' });
		expect(lastUrl()).toBe('/api/ledger/entries?q=rewe&limit=100');
		await listEntries({ ...empty, q: '   ' });
		expect(lastUrl()).toBe('/api/ledger/entries?limit=100');
	});

	it('sends the category flags only away from their defaults', async () => {
		await listEntries({
			...empty,
			category_id: [3],
			category_descendants: false,
			uncategorised: true
		});
		expect(lastUrl()).toBe(
			'/api/ledger/entries?category_id=3&category_descendants=false&uncategorised=true&limit=100'
		);
	});

	it('passes the abort signal and returns the page as the API sent it', async () => {
		const controller = new AbortController();
		await expect(listEntries(empty, { signal: controller.signal })).resolves.toEqual({
			entries: [],
			total: 0,
			limit: 100,
			offset: 0
		});
		expect((fetchMock.mock.calls.at(-1) as [string, RequestInit])[1].signal).toBe(
			controller.signal
		);
	});
});

describe('getEntry', () => {
	it('reads one entry by id, its source included', async () => {
		fetchMock.mockImplementation(async () =>
			reply({ id: 42, source: { counterparty_name: 'REWE', purpose: null } })
		);

		const found = await getEntry(42);

		expect(lastUrl()).toBe('/api/ledger/entries/42');
		expect((fetchMock.mock.calls.at(-1) as [string, RequestInit])[1].method).toBe('GET');
		expect(found).toMatchObject({ id: 42, source: { counterparty_name: 'REWE' } });
	});

	it('fails with the API error when there is no such entry', async () => {
		fetchMock.mockImplementation(
			async () =>
				new Response(
					JSON.stringify({ error: { code: 'not_found', message: 'x', details: null } }),
					{
						status: 404,
						headers: { 'Content-Type': 'application/json' }
					}
				)
		);

		await expect(getEntry(9)).rejects.toMatchObject({ status: 404, code: 'not_found' });
	});
});

describe('filterQuery', () => {
	it('is empty for an empty filter', () => {
		const present = Object.entries(filterQuery(empty)).filter(
			([, value]) => value !== undefined && !(Array.isArray(value) && value.length === 0)
		);
		expect(present).toEqual([]);
	});
});

describe('the lookups', () => {
	it('unwrap categories, payees and tags', async () => {
		fetchMock.mockImplementation(async () => reply({ categories: [{ id: 1 }] }));
		await expect(listCategories()).resolves.toEqual([{ id: 1 }]);
		expect(lastUrl()).toBe('/api/ledger/categories');

		fetchMock.mockImplementation(async () => reply({ payees: [{ id: 2 }] }));
		await expect(listPayees()).resolves.toEqual([{ id: 2 }]);
		expect(lastUrl()).toBe('/api/ledger/payees');

		fetchMock.mockImplementation(async () => reply({ tags: [{ id: 3 }] }));
		await expect(listTags()).resolves.toEqual([{ id: 3 }]);
		expect(lastUrl()).toBe('/api/ledger/tags');
	});
});
