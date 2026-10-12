import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
	ApiError,
	createTag,
	listAccounts,
	listCategories,
	listEntries,
	listPayees,
	listTags,
	tagEntry,
	untagEntry
} from '#lib/api/index.js';
import { account, category, entry, tag } from '#lib/ledger/fixtures.js';
import { emptyFilter } from '#lib/ledger/filter.js';
import { LedgerStore } from './ledger.svelte.js';
import { session } from './session.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listEntries: vi.fn(),
	listAccounts: vi.fn(),
	listCategories: vi.fn(),
	listPayees: vi.fn(),
	listTags: vi.fn(),
	createTag: vi.fn(),
	tagEntry: vi.fn(),
	untagEntry: vi.fn()
}));

function page(ids: number[], total: number, offset = 0) {
	return { entries: ids.map((id) => entry({ id })), total, limit: 100, offset };
}

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

beforeEach(() => {
	vi.resetAllMocks();
	session.expire();
});

describe('LedgerStore: entries', () => {
	it('fetches the first page for a filter and holds it', async () => {
		vi.mocked(listEntries).mockResolvedValue(page([3, 2, 1], 3));
		const store = new LedgerStore();

		store.applyFilter({ ...emptyFilter(), account_id: [1] });
		expect(store.status).toBe('loading');
		await flush();

		expect(store.status).toBe('ready');
		expect(store.entries.map((e) => e.id)).toEqual([3, 2, 1]);
		expect(store.total).toBe(3);
		expect(vi.mocked(listEntries).mock.calls[0][0]).toMatchObject({ account_id: [1] });
		expect(vi.mocked(listEntries).mock.calls[0][1]).toMatchObject({ limit: 100, offset: 0 });
	});

	it('does not fetch again for the same filter (a URL echo)', async () => {
		vi.mocked(listEntries).mockResolvedValue(page([1], 1));
		const store = new LedgerStore();

		store.applyFilter(emptyFilter());
		store.applyFilter({ ...emptyFilter(), account_id: [] });
		store.applyFilter({ ...emptyFilter(), account_id: [2, 1] });
		store.applyFilter({ ...emptyFilter(), account_id: [1, 2] });
		await flush();

		expect(listEntries).toHaveBeenCalledTimes(2);
	});

	it('answers only for the latest filter: an older response arriving late is dropped', async () => {
		const first = deferred<ReturnType<typeof page>>();
		const second = deferred<ReturnType<typeof page>>();
		vi.mocked(listEntries).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
		const store = new LedgerStore();

		store.applyFilter({ ...emptyFilter(), q: 'a' });
		store.applyFilter({ ...emptyFilter(), q: 'b' });
		second.resolve(page([2], 1));
		await flush();
		first.resolve(page([1], 1));
		await flush();

		expect(store.entries.map((e) => e.id)).toEqual([2]);
		expect(store.status).toBe('ready');
		// the older request was told to stop
		expect(vi.mocked(listEntries).mock.calls[0][1]?.signal?.aborted).toBe(true);
	});

	it('ignores the failure of an older request', async () => {
		const first = deferred<ReturnType<typeof page>>();
		vi.mocked(listEntries)
			.mockReturnValueOnce(first.promise)
			.mockResolvedValueOnce(page([2], 1));
		const store = new LedgerStore();

		store.applyFilter({ ...emptyFilter(), q: 'a' });
		store.applyFilter({ ...emptyFilter(), q: 'b' });
		first.reject(new DOMException('aborted', 'AbortError'));
		await flush();

		expect(store.status).toBe('ready');
		expect(store.error).toBeNull();
	});

	it('keeps the ApiError of a failed fetch, and a retry fetches again', async () => {
		vi.mocked(listEntries)
			.mockRejectedValueOnce(new ApiError(0, 'network_error', 'down'))
			.mockResolvedValueOnce(page([1], 1));
		const store = new LedgerStore();

		store.applyFilter(emptyFilter());
		await flush();
		expect(store.status).toBe('error');
		expect(store.error?.code).toBe('network_error');
		expect(store.entries).toEqual([]);

		await store.reload();
		expect(store.status).toBe('ready');
		expect(store.error).toBeNull();
		expect(store.entries).toHaveLength(1);
	});

	it('turns an unexpected failure into a network error', async () => {
		vi.mocked(listEntries).mockRejectedValue(new TypeError('boom'));
		const store = new LedgerStore();

		store.applyFilter(emptyFilter());
		await flush();

		expect(store.error?.code).toBe('network_error');
	});
});

describe('LedgerStore: load more', () => {
	async function loaded(total: number, ids: number[]) {
		vi.mocked(listEntries).mockResolvedValueOnce(page(ids, total));
		const store = new LedgerStore();
		store.applyFilter(emptyFilter());
		await flush();
		return store;
	}

	it('appends the next page, with the offset set to the entries held', async () => {
		const store = await loaded(5, [5, 4, 3]);
		vi.mocked(listEntries).mockResolvedValueOnce(page([2, 1], 5, 3));

		await store.loadMore();

		expect(store.entries.map((e) => e.id)).toEqual([5, 4, 3, 2, 1]);
		expect(vi.mocked(listEntries).mock.calls[1][1]).toMatchObject({ offset: 3, limit: 100 });
	});

	it('does nothing once everything is held', async () => {
		const store = await loaded(2, [2, 1]);

		await store.loadMore();

		expect(listEntries).toHaveBeenCalledTimes(1);
	});

	it('keeps the entries and reports the error when a later page fails', async () => {
		const store = await loaded(5, [5, 4, 3]);
		vi.mocked(listEntries).mockRejectedValueOnce(new ApiError(500, 'http_error', 'x'));

		await store.loadMore();

		expect(store.status).toBe('ready');
		expect(store.entries).toHaveLength(3);
		expect(store.moreError?.code).toBe('http_error');
		expect(store.loadingMore).toBe(false);
	});

	it('does not run two page fetches at once', async () => {
		const store = await loaded(5, [5, 4, 3]);
		const more = deferred<ReturnType<typeof page>>();
		vi.mocked(listEntries).mockReturnValueOnce(more.promise);

		const a = store.loadMore();
		const b = store.loadMore();
		more.resolve(page([2, 1], 5, 3));
		await Promise.all([a, b]);

		expect(listEntries).toHaveBeenCalledTimes(2);
		expect(store.entries).toHaveLength(5);
	});

	it('drops a page that arrives after the filter changed', async () => {
		const store = await loaded(5, [5, 4, 3]);
		const more = deferred<ReturnType<typeof page>>();
		vi.mocked(listEntries)
			.mockReturnValueOnce(more.promise)
			.mockResolvedValueOnce(page([9], 1));

		const pending = store.loadMore();
		store.applyFilter({ ...emptyFilter(), q: 'x' });
		more.resolve(page([2, 1], 5, 3));
		await pending;
		await flush();

		expect(store.entries.map((e) => e.id)).toEqual([9]);
	});
});

describe('LedgerStore: lookups', () => {
	it('loads the four lists once', async () => {
		vi.mocked(listAccounts).mockResolvedValue([account()]);
		vi.mocked(listCategories).mockResolvedValue([category()]);
		vi.mocked(listPayees).mockResolvedValue([]);
		vi.mocked(listTags).mockResolvedValue([tag()]);
		const store = new LedgerStore();

		await store.loadLookups();
		await store.loadLookups();

		expect(listAccounts).toHaveBeenCalledTimes(1);
		expect(store.lookups.accounts.get(1)?.name).toBe('Giro');
		expect(store.lookups.categories.get(10)?.name).toBe('Groceries');
		expect(store.lookups.tags.get(30)?.name).toBe('Lisbon trip');
		expect(store.lookupsFailed).toEqual([]);
	});

	it('treats a list that cannot be loaded as empty, and says which', async () => {
		vi.mocked(listAccounts).mockResolvedValue([account()]);
		vi.mocked(listCategories).mockResolvedValue([]);
		vi.mocked(listPayees).mockResolvedValue([]);
		vi.mocked(listTags).mockRejectedValue(new ApiError(404, 'http_error', 'Not Found'));
		const store = new LedgerStore();

		await store.loadLookups();

		expect(store.lookups.tags.size).toBe(0);
		expect(store.lookups.accounts.size).toBe(1);
		expect(store.lookupsFailed).toEqual(['tags']);
	});

	it('names the active filters from the lookups', async () => {
		vi.mocked(listEntries).mockResolvedValue(page([], 0));
		vi.mocked(listAccounts).mockResolvedValue([account()]);
		vi.mocked(listCategories).mockResolvedValue([]);
		vi.mocked(listPayees).mockResolvedValue([]);
		vi.mocked(listTags).mockResolvedValue([]);
		const store = new LedgerStore();
		await store.loadLookups();

		store.applyFilter({ ...emptyFilter(), account_id: [1], q: 'rewe' });

		expect(store.activeFilters).toEqual(['Giro', '“rewe”']);
	});
});

describe('LedgerStore: the session', () => {
	it('takes locale, currency and today from the deployment configuration', () => {
		const store = new LedgerStore();
		expect(store.locale).toBe('en');
		expect(store.baseCurrency).toBe('EUR');

		session.config = {
			locale: 'de',
			base_currency: 'CHF',
			timezone: 'Europe/Berlin'
		} as never;

		expect(store.locale).toBe('de');
		expect(store.baseCurrency).toBe('CHF');
		expect(store.today).toMatch(/^\d{4}-\d{2}-\d{2}$/);
	});
});

describe('LedgerStore: tagging one entry', () => {
	async function loaded(tagFilter: number[] = []) {
		vi.mocked(listEntries).mockResolvedValue({
			entries: [entry({ id: 3 }), entry({ id: 2, tag_ids: [7] }), entry({ id: 1 })],
			total: 3,
			limit: 100,
			offset: 0
		});
		const store = new LedgerStore();
		store.applyFilter({ ...emptyFilter(), tag_id: tagFilter });
		await flush();
		return store;
	}
	const answer = (id: number, tag_ids: number[], error: string | null = null) => ({
		entry: { id, tag_ids },
		changed: true,
		settle: { error, touched_entry_ids: [] }
	});

	it('adds a tag with PUT and patches the row in place from the answer', async () => {
		const store = await loaded();
		vi.mocked(tagEntry).mockResolvedValue(answer(3, [7, 8]));

		expect(await store.setEntryTag(3, 8, true)).toBe(true);

		expect(tagEntry).toHaveBeenCalledWith(3, 8);
		expect(store.entries.map((e) => e.id)).toEqual([3, 2, 1]);
		expect(store.entries[0].tag_ids).toEqual([7, 8]);
		expect(store.notice).toBeNull();
	});

	it('removes a tag with DELETE', async () => {
		const store = await loaded();
		vi.mocked(untagEntry).mockResolvedValue(answer(2, []));

		await store.setEntryTag(2, 7, false);

		expect(untagEntry).toHaveBeenCalledWith(2, 7);
		expect(store.entries[1].tag_ids).toEqual([]);
	});

	it('keeps a row that an active tag filter no longer matches, and marks it', async () => {
		const store = await loaded([7]);
		vi.mocked(untagEntry).mockResolvedValue(answer(2, []));

		await store.setEntryTag(2, 7, false);

		expect(store.entries.map((e) => e.id)).toEqual([3, 2, 1]);
		expect([...store.changedIds]).toEqual([2]);
		expect(store.total).toBe(3);
	});

	it('marks nothing without a tag filter, and the marks end with a reload', async () => {
		const store = await loaded();
		vi.mocked(untagEntry).mockResolvedValue(answer(2, []));
		await store.setEntryTag(2, 7, false);
		expect(store.changedIds.size).toBe(0);

		const tagged = await loaded([7]);
		await tagged.setEntryTag(2, 7, false);
		await tagged.reload();
		await flush();
		expect(tagged.changedIds.size).toBe(0);
	});

	it('says in a quiet notice when derived figures could not be recomputed', async () => {
		const store = await loaded();
		vi.mocked(tagEntry).mockResolvedValue(answer(3, [8], 'boom'));

		await store.setEntryTag(3, 8, true);

		expect(store.entries[0].tag_ids).toEqual([8]);
		expect(store.notice).toMatchObject({ error: false });
		expect(store.notice?.text).toMatch(/stale/);
	});

	it('answers a derived entry, a vanished entry and a network failure in a notice, rows untouched', async () => {
		const store = await loaded();
		const before = store.entries;

		vi.mocked(tagEntry).mockRejectedValueOnce(
			new ApiError(409, 'conflict', 'x', { reason: 'derived_entry' })
		);
		expect(await store.setEntryTag(3, 8, true)).toBe(false);
		expect(store.notice).toEqual({ text: 'Derived entries cannot be tagged', error: true });

		vi.mocked(tagEntry).mockRejectedValueOnce(new ApiError(404, 'not_found', 'x'));
		await store.setEntryTag(3, 8, true);
		expect(store.notice?.text).toMatch(/no longer exists.*Refresh/);

		vi.mocked(tagEntry).mockRejectedValueOnce(new Error('offline'));
		await store.setEntryTag(3, 8, true);
		expect(store.notice?.text).toMatch(/could not be reached/);
		expect(store.entries).toBe(before);
	});

	it('creates a tag, adds it to the lookups without a reload, and tags the entry', async () => {
		const store = await loaded();
		vi.mocked(createTag).mockResolvedValue({
			tag: tag({ id: 40, name: 'Holiday', color: null }),
			settle: { error: null, touched_entry_ids: [] }
		});
		vi.mocked(tagEntry).mockResolvedValue(answer(3, [40]));

		expect(await store.createTagFor(3, 'Holiday')).toBe(true);

		expect(createTag).toHaveBeenCalledWith('Holiday');
		expect(store.lookups.tags.get(40)?.name).toBe('Holiday');
		expect(store.entries[0].tag_ids).toEqual([40]);
		expect(listTags).not.toHaveBeenCalled();
	});

	it('does not tag when the tag could not be created', async () => {
		const store = await loaded();
		vi.mocked(createTag).mockRejectedValue(
			new ApiError(409, 'conflict', 'x', { reason: 'duplicate_name' })
		);

		expect(await store.createTagFor(3, 'Holiday')).toBe(false);

		expect(tagEntry).not.toHaveBeenCalled();
		expect(store.notice?.text).toMatch(/already exists/);
	});
});

describe('LedgerStore: Tag all', () => {
	it('is available only for a loaded list with a filter that matches something', async () => {
		vi.mocked(listEntries).mockResolvedValue(page([2, 1], 2));
		const store = new LedgerStore();
		expect(store.tagAllReason).toMatch(/loading/);

		store.applyFilter(emptyFilter());
		await flush();
		expect(store.tagAllReason).toBe('Narrow the filter first');

		store.applyFilter({ ...emptyFilter(), q: '   ' });
		expect(store.tagAllReason).toMatch(/loading|Narrow/);

		store.applyFilter({ ...emptyFilter(), account_id: [1] });
		await flush();
		expect(store.tagAllReason).toBeNull();
	});

	it('is not available when nothing matches', async () => {
		vi.mocked(listEntries).mockResolvedValue(page([], 0));
		const store = new LedgerStore();

		store.applyFilter({ ...emptyFilter(), account_id: [1] });
		await flush();

		expect(store.tagAllReason).toBe('No entries to tag');
	});
});
