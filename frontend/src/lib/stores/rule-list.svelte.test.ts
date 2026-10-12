import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
	ApiError,
	deleteRule,
	listAccounts,
	listCategories,
	listPayees,
	listRules
} from '#lib/api/index.js';
import { preview, rule } from '#lib/rules/fixtures.js';
import { RuleListStore } from './rule-list.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listRules: vi.fn(),
	deleteRule: vi.fn(),
	listAccounts: vi.fn(),
	listCategories: vi.fn(),
	listPayees: vi.fn()
}));

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(listAccounts).mockResolvedValue([]);
	vi.mocked(listCategories).mockResolvedValue([]);
	vi.mocked(listPayees).mockResolvedValue([]);
});

describe('RuleListStore', () => {
	it('loads the rules and the lists they resolve against', async () => {
		vi.mocked(listRules).mockResolvedValue([rule({ id: 1 }), rule({ id: 2 })]);
		const store = new RuleListStore();

		await store.load();

		expect(store.status).toBe('ready');
		expect(store.rules.map((r) => r.id)).toEqual([1, 2]);
		expect(store.lookupsFailed).toEqual([]);
	});

	it('names a lookup list that could not be loaded, and still shows the rules', async () => {
		vi.mocked(listRules).mockResolvedValue([rule()]);
		vi.mocked(listPayees).mockRejectedValue(new ApiError(500, 'internal', 'x'));
		const store = new RuleListStore();

		await store.load();

		expect(store.status).toBe('ready');
		expect(store.lookupsFailed).toEqual(['payees']);
	});

	it('reports a failure to load the rules, to be retried', async () => {
		vi.mocked(listRules).mockRejectedValue(new ApiError(0, 'network_error', 'x'));
		const store = new RuleListStore();

		await store.load();

		expect(store.status).toBe('error');
		expect(store.error?.kind).toBe('network');
	});

	it('takes a deleted rule out of the list in place and says what settled', async () => {
		vi.mocked(listRules).mockResolvedValue([rule({ id: 1 }), rule({ id: 2, name: 'Rent' })]);
		const store = new RuleListStore();
		await store.load();
		vi.mocked(deleteRule).mockResolvedValueOnce({
			dry_run: true,
			rule: rule({ id: 2 }),
			deleted: false,
			settle: null,
			preview: preview()
		});
		await store.remove.start(rule({ id: 2, name: 'Rent' }));
		vi.mocked(deleteRule).mockResolvedValueOnce({
			dry_run: false,
			rule: rule({ id: 2 }),
			deleted: true,
			settle: { touched_entry_ids: [4], error: null },
			preview: preview()
		});

		await store.remove.confirm();

		expect(store.rules.map((r) => r.id)).toEqual([1]);
		expect(store.notice).toBe('Rule “Rent” deleted. Settling touched 1 entry.');
	});
});
