import { flushSync } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	getQueue,
	getStatement,
	listAccounts,
	listDocuments,
	listEntries,
	listRuns,
	readChanges,
	type ChangeRead
} from '#lib/api/index.js';
import { account, entry } from '#lib/ledger/fixtures.js';
import { queue as queueFixture } from '#lib/units/fixtures.js';
import { lookupsStore } from './lookups.svelte.js';
import { AccountPageStore } from './account-page.svelte.js';
import { changes, ChangeWatcher } from './changes.svelte.js';
import { DocumentsStore } from './documents.svelte.js';
import { LedgerStore } from './ledger.svelte.js';
import { NewDataWatch, refetchOnChange } from './new-data.svelte.js';
import { ReviewQueueStore } from './review-queue.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listEntries: vi.fn(),
	listAccounts: vi.fn(),
	listDocuments: vi.fn(),
	getStatement: vi.fn(),
	getQueue: vi.fn(),
	listRuns: vi.fn(),
	readChanges: vi.fn()
}));

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const values = (over: Partial<ChangeRead> = {}): ChangeRead => ({
	ledger: 'b:1',
	documents: 'b:1',
	accounts: { '7': 'b:1' },
	active_task: null,
	...over
});

/** a poll that finds these values */
async function poll(over: Partial<ChangeRead> = {}): Promise<void> {
	vi.mocked(readChanges).mockResolvedValue(values(over));
	await changes.read();
}

beforeEach(async () => {
	vi.resetAllMocks();
	vi.mocked(readChanges).mockResolvedValue(values());
	changes.start();
	await flush();
});

afterEach(() => changes.stop());

describe('NewDataWatch', () => {
	it('is stale once its key moved since the value it took, and fresh again when it takes the current one', async () => {
		const watch = new NewDataWatch('ledger');
		expect(watch.stale).toBe(false);

		await poll({ ledger: 'b:2' });
		expect(watch.stale).toBe(true);

		watch.take();
		expect(watch.stale).toBe(false);
	});

	it('is not stale for changes that were there before the view existed', async () => {
		await poll({ ledger: 'b:9' });
		expect(new NewDataWatch('ledger').stale).toBe(false);
	});

	it('is its own: a watcher of another instance does not move it', () => {
		const other = new ChangeWatcher();
		expect(new NewDataWatch('ledger', other).stale).toBe(false);
	});
});

describe('refetchOnChange', () => {
	it('fetches again when the value moves, not on mount and not when it stays', async () => {
		const reload = vi.fn();
		const stop = $effect.root(() => refetchOnChange('ledger', reload));
		try {
			expect(reload).not.toHaveBeenCalled();

			await poll();
			flushSync();
			expect(reload).not.toHaveBeenCalled();

			await poll({ ledger: 'b:2' });
			flushSync();
			expect(reload).toHaveBeenCalledTimes(1);
		} finally {
			stop();
		}
	});

	it('does not fetch for the first value the watcher ever reads', async () => {
		changes.stop();
		const reload = vi.fn();
		const stop = $effect.root(() => refetchOnChange('ledger', reload));
		try {
			changes.start();
			await flush();
			flushSync();
			expect(reload).not.toHaveBeenCalled();
		} finally {
			stop();
		}
	});
});

describe('the views that hold a snapshot', () => {
	it('the ledger list shows the news when the ledger moved, and a reload takes the value', async () => {
		vi.mocked(listEntries).mockResolvedValue({
			entries: [entry({ id: 1 })],
			total: 1,
			limit: 100,
			offset: 0
		});
		const store = new LedgerStore();
		await store.reload();
		expect(store.news.stale).toBe(false);

		await poll({ ledger: 'b:2' });
		expect(store.news.stale).toBe(true);

		await store.reload();
		expect(store.news.stale).toBe(false);
	});

	it('the ledger list does not show the news for documents or an account', async () => {
		vi.mocked(listEntries).mockResolvedValue({ entries: [], total: 0, limit: 100, offset: 0 });
		const store = new LedgerStore();
		await store.reload();

		await poll({ documents: 'b:2', accounts: { '7': 'b:2' } });
		expect(store.news.stale).toBe(false);
	});

	it('the review queue shares the ledger key', async () => {
		vi.mocked(getQueue).mockResolvedValue(queueFixture());
		const store = new ReviewQueueStore();
		await store.load();
		expect(store.news.stale).toBe(false);

		await poll({ ledger: 'b:2' });
		expect(store.news.stale).toBe(true);

		await store.load();
		expect(store.news.stale).toBe(false);
	});

	it('the documents list is keyed on the documents, and a reload takes the value', async () => {
		vi.mocked(listDocuments).mockResolvedValue({ documents: [], total: 0, limit: 50, offset: 0 });
		const store = new DocumentsStore();
		await store.reload();
		expect(store.news.stale).toBe(false);

		await poll({ ledger: 'b:2' });
		expect(store.news.stale).toBe(false);

		await poll({ ledger: 'b:2', documents: 'b:2' });
		expect(store.news.stale).toBe(true);

		await store.reload();
		expect(store.news.stale).toBe(false);
	});

	it('the account page is keyed on its account, and the header, facts and statement are read together', async () => {
		vi.mocked(listAccounts).mockResolvedValue([account({ id: 7 })]);
		vi.mocked(getStatement).mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
		vi.mocked(listRuns).mockResolvedValue([]);
		const store = new AccountPageStore();
		await store.open(7);
		await flush();
		expect(store.news.stale).toBe(false);

		// another account, and the ledger as a whole, are not this page's news
		await poll({ ledger: 'b:2', accounts: { '7': 'b:1', '8': 'b:2' } });
		expect(store.news.stale).toBe(false);

		await poll({ ledger: 'b:2', accounts: { '7': 'b:2', '8': 'b:2' } });
		expect(store.news.stale).toBe(true);

		await store.afterWrite();
		expect(store.news.stale).toBe(false);
		// the facts and the statement were read again, together
		expect(vi.mocked(listAccounts)).toHaveBeenCalledTimes(2);
		expect(vi.mocked(getStatement)).toHaveBeenCalledTimes(2);
	});

	it('the statement is not read again because the shared accounts were refreshed', async () => {
		vi.mocked(listAccounts).mockResolvedValue([account({ id: 7 })]);
		vi.mocked(getStatement).mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
		vi.mocked(listRuns).mockResolvedValue([]);
		const store = new AccountPageStore();
		await store.open(7);
		await flush();
		await poll({ accounts: { '7': 'b:2' } });

		lookupsStore.setAccounts([account({ id: 7, name: 'Renamed' })]);
		await flush();

		expect(vi.mocked(getStatement)).toHaveBeenCalledTimes(1);
		expect(vi.mocked(listAccounts)).toHaveBeenCalledTimes(1);
		expect(store.news.stale).toBe(true);
	});

	it('a change that lands while a view is fetching is still news to it', async () => {
		let release!: () => void;
		vi.mocked(listEntries).mockImplementation(
			() =>
				new Promise((resolve) => {
					release = () => resolve({ entries: [], total: 0, limit: 100, offset: 0 });
				})
		);
		const store = new LedgerStore();
		const loading = store.reload();
		await poll({ ledger: 'b:2' });
		release();
		await loading;

		expect(store.news.stale).toBe(true);
	});
});
