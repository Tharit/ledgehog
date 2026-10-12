import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { findEntry } from './entries.js';

const fetchMock = vi.fn();

function page(ids: number[], total: number) {
	return new Response(
		JSON.stringify({ entries: ids.map((id) => ({ id })), total, limit: 500, offset: 0 }),
		{ status: 200, headers: { 'Content-Type': 'application/json' } }
	);
}

function urls(): string[] {
	return fetchMock.mock.calls.map((call) => (call as [string])[0]);
}

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('findEntry', () => {
	it('narrows the list by day and account when it knows them', async () => {
		fetchMock.mockResolvedValue(page([3, 42, 7], 3));

		const found = await findEntry(42, { on: '2026-10-09', accountId: 2 });

		expect(found).toMatchObject({ id: 42 });
		expect(urls()).toHaveLength(1);
		expect(urls()[0]).toContain('from=2026-10-09');
		expect(urls()[0]).toContain('to=2026-10-09');
		expect(urls()[0]).toContain('account_id=2');
		expect(urls()[0]).toContain('limit=500');
	});

	it('goes on to the next page until it finds the entry', async () => {
		fetchMock.mockResolvedValueOnce(page([1, 2], 600)).mockResolvedValueOnce(page([42], 600));

		const found = await findEntry(42);

		expect(found).toMatchObject({ id: 42 });
		expect(urls()[1]).toContain('offset=500');
	});

	it('stops at the end of the list and says it found nothing', async () => {
		fetchMock.mockResolvedValue(page([1, 2], 2));

		expect(await findEntry(42, { on: '2026-10-09' })).toBeNull();
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});
});
