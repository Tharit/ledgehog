import { flushSync } from 'svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getStatement, listAccounts, listEntries, listRuns } from '#lib/api/index.js';
import { account, entry } from '#lib/ledger/fixtures.js';
import { AccountPageStore } from './account-page.svelte.js';
import { LedgerStore } from './ledger.svelte.js';
import { NewDataWatch, refetchOnSyncEnd } from './new-data.svelte.js';
import { sync } from './sync.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listEntries: vi.fn(),
	listAccounts: vi.fn(),
	getStatement: vi.fn(),
	listRuns: vi.fn()
}));

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
	vi.resetAllMocks();
});

describe('NewDataWatch', () => {
	it('is stale once rows arrived since the revision it took, and fresh again when it takes the current one', () => {
		const source = { dataRevision: 3, endRevision: 0 };
		const watch = new NewDataWatch(source);
		expect(watch.stale).toBe(false);

		source.dataRevision = 4;
		expect(watch.stale).toBe(true);

		watch.take();
		expect(watch.stale).toBe(false);
	});

	it('is not stale for rows that arrived before the view existed', () => {
		expect(new NewDataWatch({ dataRevision: 9, endRevision: 0 }).stale).toBe(false);
	});
});

describe('refetchOnSyncEnd', () => {
	it('fetches again when a sync ends, not on mount and not for rows written meanwhile', () => {
		const source = $state({ dataRevision: 0, endRevision: 0 });
		const reload = vi.fn();
		const stop = $effect.root(() => refetchOnSyncEnd(reload, source));
		try {
			expect(reload).not.toHaveBeenCalled();

			source.dataRevision = 1;
			flushSync();
			expect(reload).not.toHaveBeenCalled();

			source.endRevision = 1;
			flushSync();
			expect(reload).toHaveBeenCalledTimes(1);
		} finally {
			stop();
		}
	});
});

describe('the views that hold a snapshot', () => {
	it('the ledger list shows the news after a sync wrote rows, and a reload takes the revision', async () => {
		vi.mocked(listEntries).mockResolvedValue({
			entries: [entry({ id: 1 })],
			total: 1,
			limit: 100,
			offset: 0
		});
		const store = new LedgerStore();
		await store.reload();
		expect(store.news.stale).toBe(false);

		sync.dataRevision++;
		expect(store.news.stale).toBe(true);

		await store.reload();
		expect(store.news.stale).toBe(false);
	});

	it('the account page takes the revision when the header, facts and statement are read together', async () => {
		vi.mocked(listAccounts).mockResolvedValue([account({ id: 7 })]);
		vi.mocked(getStatement).mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
		vi.mocked(listRuns).mockResolvedValue([]);
		const store = new AccountPageStore();
		await store.open(7);
		await flush();
		expect(store.news.stale).toBe(false);

		sync.dataRevision++;
		expect(store.news.stale).toBe(true);

		await store.afterWrite();
		expect(store.news.stale).toBe(false);
		// the facts and the statement were read again, together
		expect(vi.mocked(listAccounts)).toHaveBeenCalledTimes(2);
	});

	it('rows that arrive while a view is fetching are still news to it', async () => {
		let release!: () => void;
		vi.mocked(listEntries).mockImplementation(
			() =>
				new Promise((resolve) => {
					release = () => resolve({ entries: [], total: 0, limit: 100, offset: 0 });
				})
		);
		const store = new LedgerStore();
		const loading = store.reload();
		sync.dataRevision++;
		release();
		await loading;

		expect(store.news.stale).toBe(true);
	});
});
