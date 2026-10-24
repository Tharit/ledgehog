import { flushSync } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getByCategory, getOverview, readChanges } from '#lib/api/index.js';
import { todayIso } from '#lib/format/index.js';
import { byCategory, overview } from '#lib/reports/fixtures.js';
import { changes } from './changes.svelte.js';
import { refetchOnChange } from './new-data.svelte.js';
import { OverviewStore, TOP_CATEGORIES } from './overview.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	getOverview: vi.fn(),
	getByCategory: vi.fn(),
	readChanges: vi.fn()
}));

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (error: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const values = (ledger: string) => ({
	ledger,
	documents: 'b:1',
	accounts: {},
	active_task: null,
	model_pending: 0,
	model_pending_lines: 0
});

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(getOverview).mockResolvedValue(overview());
	vi.mocked(getByCategory).mockResolvedValue(byCategory());
});

describe('OverviewStore', () => {
	it('starts on the skeleton and shows both answers once they arrive', async () => {
		const store = new OverviewStore();
		expect(store.status).toBe('loading');
		expect(store.overview).toBeNull();

		await store.load();

		expect(store.status).toBe('ready');
		expect(store.categoriesStatus).toBe('ready');
		expect(store.overview?.as_of).toBe('2026-10-20');
		expect(store.byCategory?.kind).toBe('expense');
	});

	it('asks for the top expense categories of the month so far', async () => {
		await new OverviewStore().load();

		const today = todayIso('UTC');
		expect(getByCategory).toHaveBeenCalledWith({
			from: `${today.slice(0, 8)}01`,
			to: today,
			kind: 'expense',
			top: TOP_CATEGORIES
		});
	});

	it('keeps the figures on screen while it reads again, and replaces them when the answer arrives', async () => {
		const store = new OverviewStore();
		await store.load();
		const again = deferred<ReturnType<typeof overview>>();
		vi.mocked(getOverview).mockReturnValue(again.promise);

		const reading = store.load();
		await flush();
		expect(store.status).toBe('ready');
		expect(store.overview?.net_worth.total?.amount).toBe(12845000);

		again.resolve(
			overview({
				net_worth: { ...overview().net_worth, total: { amount: 1, currency: 'EUR' } }
			})
		);
		await reading;
		expect(store.overview?.net_worth.total?.amount).toBe(1);
		expect(store.status).toBe('ready');
	});

	it('drops an answer that is not the latest read', async () => {
		const store = new OverviewStore();
		const first = deferred<ReturnType<typeof overview>>();
		vi.mocked(getOverview).mockReturnValueOnce(first.promise);
		const stale = store.load();
		await store.load();

		first.resolve(overview({ as_of: '2020-01-01' }));
		await stale;

		expect(store.overview?.as_of).toBe('2026-10-20');
	});

	it('says so when the first read fails, and reads again on retry', async () => {
		vi.mocked(getOverview).mockRejectedValueOnce(new ApiError(500, 'internal_error', 'x'));
		const store = new OverviewStore();

		await store.load();
		expect(store.status).toBe('error');
		expect(store.error?.code).toBe('internal_error');

		await store.retry();
		expect(store.status).toBe('ready');
		expect(store.error).toBeNull();
	});

	it('keeps the figures held when a later read fails', async () => {
		const store = new OverviewStore();
		await store.load();
		vi.mocked(getOverview).mockRejectedValue(new Error('offline'));
		vi.mocked(getByCategory).mockRejectedValue(new Error('offline'));

		await store.load();

		expect(store.status).toBe('ready');
		expect(store.categoriesStatus).toBe('ready');
		expect(store.overview?.as_of).toBe('2026-10-20');
		expect(store.byCategory).not.toBeNull();
	});

	it('fails the categories card alone', async () => {
		vi.mocked(getByCategory).mockRejectedValue(new Error('offline'));
		const store = new OverviewStore();

		await store.load();

		expect(store.status).toBe('ready');
		expect(store.categoriesStatus).toBe('error');
	});
});

describe('the Overview refetches when the ledger moves', () => {
	beforeEach(async () => {
		vi.mocked(readChanges).mockResolvedValue(values('b:1'));
		changes.start();
		await changes.read();
	});
	afterEach(() => changes.stop());

	it('reads again on a new ledger value and keeps its figures meanwhile', async () => {
		const store = new OverviewStore();
		await store.load();
		const stop = $effect.root(() => refetchOnChange('ledger', () => void store.load()));
		try {
			expect(getOverview).toHaveBeenCalledTimes(1);

			const again = deferred<ReturnType<typeof overview>>();
			vi.mocked(getOverview).mockReturnValue(again.promise);
			vi.mocked(readChanges).mockResolvedValue(values('b:2'));
			await changes.read();
			flushSync();

			expect(getOverview).toHaveBeenCalledTimes(2);
			expect(store.status).toBe('ready');
			expect(store.overview?.as_of).toBe('2026-10-20');

			again.resolve(overview({ as_of: '2026-10-21' }));
			await flush();
			expect(store.overview?.as_of).toBe('2026-10-21');
		} finally {
			stop();
		}
	});
});
