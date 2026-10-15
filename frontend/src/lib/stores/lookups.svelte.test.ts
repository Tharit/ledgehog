import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, listAccounts, listCategories, listPayees, listTags } from '#lib/api/index.js';
import { account, category, payee, tag } from '#lib/ledger/fixtures.js';
import { LookupsStore, lookupsStore } from './lookups.svelte.js';
import { session } from './session.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listAccounts: vi.fn(),
	listCategories: vi.fn(),
	listPayees: vi.fn(),
	listTags: vi.fn()
}));

function lists() {
	vi.mocked(listAccounts).mockResolvedValue([account()]);
	vi.mocked(listCategories).mockResolvedValue([category()]);
	vi.mocked(listPayees).mockResolvedValue([payee()]);
	vi.mocked(listTags).mockResolvedValue([tag()]);
}

beforeEach(() => {
	vi.resetAllMocks();
	lists();
});

describe('LookupsStore: addAccount', () => {
	it('adds the account to the shared list without a request and keeps the rest', async () => {
		const store = new LookupsStore();
		await store.ensure();
		vi.mocked(listAccounts).mockClear();

		store.addAccount(account({ id: 8, name: 'Cash USD', currency: 'USD' }));

		expect(store.lookups.accounts.get(8)?.name).toBe('Cash USD');
		expect(store.lookups.accounts.get(1)?.name).toBe('Giro');
		expect(store.lookups.payees.get(20)?.name).toBe('REWE');
		expect(listAccounts).not.toHaveBeenCalled();
	});
});

describe('LookupsStore', () => {
	it('loads the four lists once, however many screens ask', async () => {
		const store = new LookupsStore();

		await Promise.all([store.ensure(), store.ensure()]);
		await store.ensure();

		expect(listAccounts).toHaveBeenCalledTimes(1);
		expect(store.lookups.accounts.get(1)?.name).toBe('Giro');
		expect(store.lookups.payees.get(20)?.name).toBe('REWE');
		expect(store.failed).toEqual([]);
		expect(store.loaded).toBe(true);
	});

	it('names a list that failed and keeps it empty', async () => {
		vi.mocked(listTags).mockRejectedValue(new ApiError(500, 'internal', 'x'));
		const store = new LookupsStore();

		await store.ensure();

		expect(store.failed).toEqual(['tags']);
		expect(store.lookups.tags.size).toBe(0);
		expect(store.lookups.accounts.size).toBe(1);
	});

	it('reload fetches everything again; a list that fails keeps its old value', async () => {
		const store = new LookupsStore();
		await store.ensure();
		vi.mocked(listCategories).mockResolvedValue([category({ id: 11, name: 'Rent' })]);
		vi.mocked(listPayees).mockRejectedValue(new ApiError(0, 'network_error', 'x'));

		await store.reload();

		expect(store.lookups.categories.get(11)?.name).toBe('Rent');
		expect(store.lookups.categories.has(10)).toBe(false);
		expect(store.lookups.payees.get(20)?.name).toBe('REWE');
		expect(store.failed).toEqual(['payees']);
	});

	it('takes over the lists the settings screens fetched, and tags created elsewhere', async () => {
		const store = new LookupsStore();
		await store.ensure();

		store.setCategories([category({ id: 12, name: 'Travel' })]);
		store.setPayees([]);
		store.addTag(tag({ id: 31, name: 'Tax' }));

		expect(store.lookups.categories.get(12)?.name).toBe('Travel');
		expect(store.lookups.payees.size).toBe(0);
		expect(store.lookups.tags.get(31)?.name).toBe('Tax');
		expect(store.lookups.tags.get(30)?.name).toBe('Lisbon trip');
		expect(listCategories).toHaveBeenCalledTimes(1);
	});

	it('reloads only the tags on request', async () => {
		const store = new LookupsStore();
		await store.ensure();
		vi.mocked(listTags).mockResolvedValue([tag({ id: 40, name: 'New' })]);

		await store.reloadTags();

		expect([...store.lookups.tags.keys()]).toEqual([40]);
		expect(listAccounts).toHaveBeenCalledTimes(1);
	});

	it('is forgotten when the session ends', async () => {
		await lookupsStore.ensure();
		expect(lookupsStore.loaded).toBe(true);

		session.expire();

		expect(lookupsStore.loaded).toBe(false);
		expect(lookupsStore.lookups.accounts.size).toBe(0);
	});
});
