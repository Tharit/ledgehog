import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
	ApiError,
	listImporters,
	listInstances,
	listRuns,
	type ImportRun
} from '#lib/api/index.js';
import { AccountRunsStore } from './account-runs.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listRuns: vi.fn(),
	listInstances: vi.fn(),
	listImporters: vi.fn()
}));

function page(ids: number[], total: number, offset = 0) {
	return { runs: ids.map((id) => ({ id }) as ImportRun), total, limit: 100, offset };
}

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(listInstances).mockResolvedValue([]);
	vi.mocked(listImporters).mockResolvedValue([]);
});

describe('AccountRunsStore paging', () => {
	it('loads the first page, appends the next at the offset held, and stops at the total', async () => {
		vi.mocked(listRuns).mockResolvedValueOnce(page([5, 4], 3));
		const store = new AccountRunsStore();
		await store.load(7);
		expect(store.runs.map((r) => r.id)).toEqual([5, 4]);
		expect(store.total).toBe(3);
		expect(vi.mocked(listRuns).mock.calls[0][0]).toMatchObject({ accountId: 7, limit: 100 });

		vi.mocked(listRuns).mockResolvedValueOnce(page([3], 3, 2));
		await store.loadMore();
		expect(store.runs.map((r) => r.id)).toEqual([5, 4, 3]);
		expect(vi.mocked(listRuns).mock.calls[1][0]).toMatchObject({ accountId: 7, offset: 2 });

		await store.loadMore();
		expect(listRuns).toHaveBeenCalledTimes(2);
	});

	it('keeps the runs held when a load more fails, and says so', async () => {
		vi.mocked(listRuns).mockResolvedValueOnce(page([5], 2));
		const store = new AccountRunsStore();
		await store.load(7);
		vi.mocked(listRuns).mockRejectedValueOnce(new ApiError(500, 'internal', 'x'));
		await store.loadMore();
		expect(store.moreFailed).toBe(true);
		expect(store.runs.map((r) => r.id)).toEqual([5]);
		expect(store.loadingMore).toBe(false);
	});

	it('a reload after a write is the first page again', async () => {
		vi.mocked(listRuns).mockResolvedValueOnce(page([5, 4], 3));
		const store = new AccountRunsStore();
		await store.load(7);
		vi.mocked(listRuns).mockResolvedValueOnce(page([6, 5], 4));
		await store.reload();
		expect(store.runs.map((r) => r.id)).toEqual([6, 5]);
		expect(store.total).toBe(4);
		expect(vi.mocked(listRuns).mock.calls[1][0]).not.toHaveProperty('offset');
	});
});
