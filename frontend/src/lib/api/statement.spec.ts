import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearDuplicate, getProvenance, getStatement, markDuplicate } from './statement.js';

const fetchMock = vi.fn();

function reply(payload: unknown, status = 200): Response {
	return new Response(JSON.stringify(payload), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

function last(): [string, RequestInit] {
	return fetchMock.mock.calls.at(-1) as [string, RequestInit];
}

beforeEach(() => {
	fetchMock.mockReset();
	fetchMock.mockImplementation(async () => reply({}));
	vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe('the statement and provenance reads', () => {
	it('pages the statement and filters by amount', async () => {
		await getStatement(3, { limit: 100, offset: 200, amount: -4000 });
		expect(last()[0]).toBe('/api/ledger/accounts/3/statement?limit=100&offset=200&amount=-4000');
	});

	it('leaves out what it was not given', async () => {
		await getStatement(3);
		expect(last()[0]).toBe('/api/ledger/accounts/3/statement');
	});

	it('reads provenance by source id', async () => {
		await getProvenance(8);
		expect(last()[0]).toBe('/api/ledger/sources/8');
	});
});

describe('the duplicate routes', () => {
	it('previews a marking with a dry run and no versions', async () => {
		await markDuplicate(8, 5, { dryRun: true });
		expect(last()[0]).toBe('/api/ledger/sources/8/duplicate');
		expect(JSON.parse(last()[1].body as string)).toEqual({
			of: 5,
			dry_run: true,
			expected_versions: null
		});
	});

	it('sends no versions on a dry run even when it is given some', async () => {
		await markDuplicate(8, 5, { dryRun: true, versions: { 10: 2 } });
		expect(JSON.parse(last()[1].body as string).expected_versions).toBeNull();
	});

	it('sends no map when the caller has no versions, never an empty one', async () => {
		await markDuplicate(8, 5);
		expect(JSON.parse(last()[1].body as string).expected_versions).toBeNull();
		await markDuplicate(8, 5, { versions: {} });
		expect(JSON.parse(last()[1].body as string).expected_versions).toBeNull();
	});

	it('carries the versions the preview reported', async () => {
		await markDuplicate(8, 5, { versions: { 10: 2, 11: 1 } });
		expect(JSON.parse(last()[1].body as string)).toEqual({
			of: 5,
			dry_run: false,
			expected_versions: { '10': 2, '11': 1 }
		});
	});

	it('clears a duplicate with a post and no body', async () => {
		await clearDuplicate(8);
		expect(last()[0]).toBe('/api/ledger/sources/8/not-duplicate');
		expect(last()[1].method).toBe('POST');
	});
});
