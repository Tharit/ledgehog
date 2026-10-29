import { render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { signedIn } from '#lib/entry-form/fixtures.js';
import { account } from '#lib/ledger/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import AccountPage from './account-route.harness.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	listAccounts: vi.fn(),
	listCategories: vi.fn(),
	listPayees: vi.fn(),
	listTags: vi.fn(),
	getStatement: vi.fn(),
	readChanges: vi.fn()
}));
const importersApi = vi.hoisted(() => ({
	listRuns: vi.fn(),
	listImporters: vi.fn(),
	listInstances: vi.fn()
}));
vi.mock('#lib/api/importers.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/importers.js')>()),
	...importersApi
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));
vi.mock('$app/state', () => ({
	page: { url: new URL('http://localhost/accounts/7'), params: { id: '7' } }
}));
vi.mock('$app/navigation', () => ({
	goto: vi.fn(),
	afterNavigate: vi.fn(),
	pushState: vi.fn(),
	replaceState: vi.fn()
}));
vi.mock('#lib/units/panel-instance.js', () => ({
	unitPanel: { open: vi.fn(), unitId: null, isOpen: false }
}));

beforeEach(() => {
	vi.resetAllMocks();
	lookupsStore.reset();
	signedIn();
	api.listAccounts.mockResolvedValue([
		account({ id: 7, name: 'Giro', kind: 'checking', icon: 'piggy-bank', color: 'forest' })
	]);
	api.listCategories.mockResolvedValue([]);
	api.listPayees.mockResolvedValue([]);
	api.listTags.mockResolvedValue([]);
	api.getStatement.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
	api.readChanges.mockResolvedValue({
		ledger: 'b:1',
		documents: 'b:1',
		accounts: { '7': 'b:1' },
		active_task: null
	});
	importersApi.listRuns.mockResolvedValue({ runs: [], total: 0, limit: 100, offset: 0 });
	importersApi.listImporters.mockResolvedValue([]);
	importersApi.listInstances.mockResolvedValue([]);
});

describe('the account page header', () => {
	it("shows the account's own icon beside its title, in a comfortable tile", async () => {
		render(AccountPage);

		const title = await screen.findByRole('heading', { level: 1, name: 'Giro' });
		const header = title.closest('[data-slot="page-header"]')!;
		const tile = header.querySelector('span[style*="--tile-fg"]')!;
		await waitFor(() => expect(tile).not.toBeNull());
		expect(tile.querySelector('svg.lucide-piggy-bank')).not.toBeNull();
		expect(tile).toHaveClass('size-8');
		expect(header.querySelector('[data-slot="account-dot"]')).toBeNull();
	});
});
