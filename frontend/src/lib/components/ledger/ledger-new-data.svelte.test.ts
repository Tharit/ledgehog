import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { signedIn } from '#lib/entry-form/fixtures.js';
import { documentRow } from '#lib/documents/fixtures.js';
import { account } from '#lib/ledger/fixtures.js';
import { changes } from '#lib/stores/changes.svelte.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import AccountPage from '../../../routes/accounts/[id]/+page.svelte';
import DocumentsPage from '../../../routes/documents/+page.svelte';
import LedgerPage from '../../../routes/ledger/+page.svelte';
import ImportersPage from '../../../routes/settings/importers/+page.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	listEntries: vi.fn(),
	listAccounts: vi.fn(),
	listCategories: vi.fn(),
	listPayees: vi.fn(),
	listTags: vi.fn(),
	listDocuments: vi.fn(),
	listDocumentProviders: vi.fn(),
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
	page: { url: new URL('http://localhost/ledger'), params: { id: '7' } }
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

const base = { ledger: 'b:1', documents: 'b:1', accounts: { '7': 'b:1', '8': 'b:1' } };

/** a poll of the change watcher that finds these values */
async function poll(over: Partial<typeof base> = {}): Promise<void> {
	api.readChanges.mockResolvedValue({ ...base, ...over, active_task: null });
	await changes.read();
}

beforeEach(async () => {
	vi.resetAllMocks();
	lookupsStore.reset();
	signedIn();
	api.listEntries.mockResolvedValue({ entries: [], total: 0 });
	api.listAccounts.mockResolvedValue([account({ id: 7 })]);
	api.listCategories.mockResolvedValue([]);
	api.listPayees.mockResolvedValue([]);
	api.listTags.mockResolvedValue([]);
	api.listDocuments.mockResolvedValue({ documents: [documentRow()], total: 1 });
	api.listDocumentProviders.mockResolvedValue([]);
	api.getStatement.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
	importersApi.listRuns.mockResolvedValue([]);
	importersApi.listImporters.mockResolvedValue([]);
	importersApi.listInstances.mockResolvedValue([]);
	api.readChanges.mockResolvedValue({ ...base, active_task: null });
	changes.start();
	await changes.read();
});

afterEach(() => changes.stop());

describe('the ledger, a snapshot', () => {
	it('shows "New data — Refresh" when the ledger moved, from any source, and never refetches itself', async () => {
		render(LedgerPage);
		await waitFor(() => expect(api.listEntries).toHaveBeenCalledTimes(1));
		expect(screen.queryByText(/New data/)).toBeNull();

		// another tab, an upload or the other user wrote
		await poll({ ledger: 'b:2' });
		expect(await screen.findByText('New data —')).toBeInTheDocument();
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(api.listEntries).toHaveBeenCalledTimes(1);

		await fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
		await waitFor(() => expect(api.listEntries).toHaveBeenCalledTimes(2));
		await waitFor(() => expect(screen.queryByText(/New data/)).toBeNull());
	});

	it('says nothing for a change of the documents only', async () => {
		render(LedgerPage);
		await waitFor(() => expect(api.listEntries).toHaveBeenCalledTimes(1));

		await poll({ documents: 'b:2' });
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(screen.queryByText(/New data/)).toBeNull();
	});
});

describe('the documents list, a snapshot', () => {
	it('shows "New data — Refresh" when the documents moved, and Refresh refetches it', async () => {
		render(DocumentsPage);
		await waitFor(() => expect(api.listDocuments).toHaveBeenCalledTimes(1));
		expect(screen.queryByText(/New data/)).toBeNull();

		await poll({ ledger: 'b:2' });
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(screen.queryByText(/New data/)).toBeNull();

		await poll({ ledger: 'b:2', documents: 'b:2' });
		expect(await screen.findByText('New data —')).toBeInTheDocument();
		expect(api.listDocuments).toHaveBeenCalledTimes(1);

		await fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
		await waitFor(() => expect(api.listDocuments).toHaveBeenCalledTimes(2));
		await waitFor(() => expect(screen.queryByText(/New data/)).toBeNull());
	});
});

describe('the account page, a snapshot of one account', () => {
	it('shows the notice for its own account only, and Refresh reads the facts and the statement again', async () => {
		render(AccountPage);
		await waitFor(() => expect(api.getStatement).toHaveBeenCalledTimes(1));
		await waitFor(() => expect(api.listAccounts).toHaveBeenCalled());
		const factsReads = api.listAccounts.mock.calls.length;

		await poll({ accounts: { '7': 'b:1', '8': 'b:2' } });
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(screen.queryByText(/New data/)).toBeNull();

		await poll({ accounts: { '7': 'b:2', '8': 'b:2' } });
		expect(await screen.findByText('New data —')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
		await waitFor(() => expect(api.getStatement).toHaveBeenCalledTimes(2));
		expect(api.listAccounts.mock.calls.length).toBeGreaterThan(factsReads);
		await waitFor(() => expect(screen.queryByText(/New data/)).toBeNull());
	});

	it('reads its runs again when the ledger moves, a list that is not a snapshot', async () => {
		render(AccountPage);
		await waitFor(() => expect(importersApi.listRuns).toHaveBeenCalled());
		const before = importersApi.listRuns.mock.calls.length;

		await poll({ ledger: 'b:2' });

		await waitFor(() => expect(importersApi.listRuns.mock.calls.length).toBeGreaterThan(before));
	});
});

describe('the importers list, which is not a snapshot', () => {
	it('is read again when the ledger moves, not for the documents, and shows no notice', async () => {
		render(ImportersPage);
		await waitFor(() => expect(importersApi.listInstances).toHaveBeenCalledTimes(1));

		await poll({ documents: 'b:2' });
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(importersApi.listInstances).toHaveBeenCalledTimes(1);

		await poll({ ledger: 'b:2', documents: 'b:2' });
		await waitFor(() => expect(importersApi.listInstances).toHaveBeenCalledTimes(2));
		expect(screen.queryByText(/New data/)).toBeNull();
	});
});
