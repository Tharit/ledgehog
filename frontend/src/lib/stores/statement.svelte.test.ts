import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getStatement } from '#lib/api/index.js';
import { recordRow, sourceRow } from '#lib/accounts/fixtures.js';
import { StatementStore } from './statement.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	getStatement: vi.fn()
}));

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function page(ids: number[], total: number, offset = 0) {
	return { items: ids.map((id) => sourceRow({ id })), total, limit: 100, offset };
}

beforeEach(() => vi.resetAllMocks());

describe('StatementStore', () => {
	it('loads the first page and holds it', async () => {
		vi.mocked(getStatement).mockResolvedValue(page([3, 2, 1], 3));
		const store = new StatementStore();

		const loading = store.load(7);
		expect(store.status).toBe('loading');
		await loading;

		expect(store.status).toBe('ready');
		expect(store.items.map((i) => i.id)).toEqual([3, 2, 1]);
		expect(store.total).toBe(3);
		expect(vi.mocked(getStatement).mock.calls[0][0]).toBe(7);
		expect(vi.mocked(getStatement).mock.calls[0][1]).toMatchObject({ limit: 100, offset: 0 });
	});

	it('says why the first page failed', async () => {
		vi.mocked(getStatement).mockRejectedValue(new ApiError(500, 'internal', 'x'));
		const store = new StatementStore();
		await store.load(7);
		expect(store.status).toBe('error');
		expect(store.error?.code).toBe('internal');
	});

	it('appends the next page at the offset of the rows held', async () => {
		vi.mocked(getStatement).mockResolvedValueOnce(page([5, 4], 4));
		const store = new StatementStore();
		await store.load(7);
		vi.mocked(getStatement).mockResolvedValueOnce(page([3, 2], 4, 2));

		await store.loadMore();

		expect(vi.mocked(getStatement).mock.calls[1][1]).toMatchObject({ offset: 2 });
		expect(store.items.map((i) => i.id)).toEqual([5, 4, 3, 2]);
	});

	it('keeps the rows held when more cannot be loaded', async () => {
		vi.mocked(getStatement).mockResolvedValueOnce(page([5, 4], 4));
		const store = new StatementStore();
		await store.load(7);
		vi.mocked(getStatement).mockRejectedValueOnce(new ApiError(0, 'network_error', 'x'));

		await store.loadMore();

		expect(store.items).toHaveLength(2);
		expect(store.moreError?.code).toBe('network_error');
	});

	it('does not ask for more when everything is held', async () => {
		vi.mocked(getStatement).mockResolvedValue(page([1], 1));
		const store = new StatementStore();
		await store.load(7);
		await store.loadMore();
		expect(getStatement).toHaveBeenCalledTimes(1);
	});

	describe('refetch', () => {
		it('replaces the rows held, whole, with the answer of the server', async () => {
			vi.mocked(getStatement).mockResolvedValueOnce(page([3, 2, 1], 3));
			const store = new StatementStore();
			await store.load(7);
			vi.mocked(getStatement).mockResolvedValueOnce({
				items: [
					recordRow({ id: 9 }),
					sourceRow({ id: 3, balance: { amount: 1, currency: 'EUR' } })
				],
				total: 2,
				limit: 100,
				offset: 0
			});

			await store.refetch();

			expect(store.items.map((i) => `${i.kind}:${i.id}`)).toEqual(['record:9', 'source:3']);
			expect(store.total).toBe(2);
			expect(store.refetching).toBe(false);
		});

		it('asks for as many rows as it holds, in pages of at most 500', async () => {
			const many = Array.from({ length: 600 }, (_, i) => 1000 - i);
			vi.mocked(getStatement)
				.mockResolvedValueOnce(page(many.slice(0, 100), 1000))
				.mockResolvedValueOnce(page(many.slice(100, 200), 1000, 100))
				.mockResolvedValueOnce(page(many.slice(200, 300), 1000, 200))
				.mockResolvedValueOnce(page(many.slice(300, 400), 1000, 300))
				.mockResolvedValueOnce(page(many.slice(400, 500), 1000, 400))
				.mockResolvedValueOnce(page(many.slice(500, 600), 1000, 500));
			const store = new StatementStore();
			await store.load(7);
			for (let i = 0; i < 5; i++) await store.loadMore();
			expect(store.items).toHaveLength(600);
			vi.mocked(getStatement).mockClear();
			vi.mocked(getStatement)
				.mockResolvedValueOnce(page(many.slice(0, 500), 1000))
				.mockResolvedValueOnce(page(many.slice(500, 600), 1000, 500));

			await store.refetch();

			const calls = vi.mocked(getStatement).mock.calls.map((c) => c[1]);
			expect(calls).toMatchObject([
				{ limit: 500, offset: 0 },
				{ limit: 100, offset: 500 }
			]);
			expect(store.items).toHaveLength(600);
		});

		it('keeps what it holds and says so when the refetch fails', async () => {
			vi.mocked(getStatement).mockResolvedValueOnce(page([2, 1], 2));
			const store = new StatementStore();
			await store.load(7);
			vi.mocked(getStatement).mockRejectedValueOnce(new ApiError(0, 'network_error', 'x'));

			await store.refetch();

			expect(store.items).toHaveLength(2);
			expect(store.refetchFailed).toBe(true);
		});

		it('is dropped when another account is loaded meanwhile', async () => {
			vi.mocked(getStatement).mockResolvedValueOnce(page([2, 1], 2));
			const store = new StatementStore();
			await store.load(7);
			let release!: (v: ReturnType<typeof page>) => void;
			vi.mocked(getStatement).mockReturnValueOnce(new Promise((r) => (release = r)));
			const refetching = store.refetch();
			vi.mocked(getStatement).mockResolvedValueOnce(page([9], 1));
			await store.load(8);
			release(page([2], 1));
			await refetching;
			await flush();

			expect(store.items.map((i) => i.id)).toEqual([9]);
		});
	});
});
