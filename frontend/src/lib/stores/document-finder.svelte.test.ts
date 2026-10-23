import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, listDocuments } from '#lib/api/index.js';
import { documentRow } from '#lib/documents/fixtures.js';
import { DocumentFinder, FINDER_DELAY_MS, FINDER_LIMIT } from './document-finder.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listDocuments: vi.fn()
}));

const page = (ids: number[]) => ({
	documents: ids.map((id) => documentRow({ id })),
	total: ids.length,
	limit: FINDER_LIMIT,
	offset: 0
});

const settle = async () => {
	for (let i = 0; i < 5; i++) await Promise.resolve();
};

beforeEach(() => {
	vi.useFakeTimers();
	vi.resetAllMocks();
});
afterEach(() => vi.useRealTimers());

describe('DocumentFinder', () => {
	it('lists the provider’s documents that no entry carries, at once when asked to', async () => {
		vi.mocked(listDocuments).mockResolvedValue(page([3, 2]));
		const finder = new DocumentFinder();

		finder.search('amazon', '', true);
		expect(finder.status).toBe('loading');
		await settle();

		expect(listDocuments).toHaveBeenCalledWith(
			{ provider: ['amazon'], q: '', fully_charged: false },
			expect.objectContaining({ limit: FINDER_LIMIT })
		);
		expect(finder.status).toBe('ready');
		expect(finder.documents.map((d) => d.id)).toEqual([3, 2]);
		expect(finder.total).toBe(2);
	});

	it('waits for typing to rest, and asks once for the last text', async () => {
		vi.mocked(listDocuments).mockResolvedValue(page([1]));
		const finder = new DocumentFinder();

		finder.search('amazon', 'a');
		await vi.advanceTimersByTimeAsync(100);
		finder.search('amazon', ' ab ');
		await vi.advanceTimersByTimeAsync(FINDER_DELAY_MS - 1);
		expect(listDocuments).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(1);

		expect(listDocuments).toHaveBeenCalledTimes(1);
		expect(vi.mocked(listDocuments).mock.calls[0][0].q).toBe('ab');
	});

	it('shows the latest answer: an older one that arrives late is discarded', async () => {
		let late!: (value: ReturnType<typeof page>) => void;
		vi.mocked(listDocuments)
			.mockImplementationOnce(() => new Promise((resolve) => (late = resolve)))
			.mockResolvedValueOnce(page([9]));
		const finder = new DocumentFinder();

		finder.search('amazon', 'x', true);
		finder.search('amazon', 'y', true);
		await settle();
		late(page([1]));
		await settle();

		expect(finder.documents.map((d) => d.id)).toEqual([9]);
	});

	it('says it failed', async () => {
		vi.mocked(listDocuments).mockRejectedValue(new ApiError(500, 'internal', 'x'));
		const finder = new DocumentFinder();

		finder.search('amazon', '', true);
		await settle();

		expect(finder.status).toBe('error');
		expect(finder.error?.status).toBe(500);
	});

	it('lets nothing land after it is disposed', async () => {
		let resolve!: (value: ReturnType<typeof page>) => void;
		vi.mocked(listDocuments).mockImplementation(() => new Promise((r) => (resolve = r)));
		const finder = new DocumentFinder();

		finder.search('amazon', '', true);
		finder.dispose();
		resolve(page([1]));
		await settle();

		expect(finder.status).toBe('idle');
		expect(finder.documents).toEqual([]);
	});
});
