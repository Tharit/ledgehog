import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { entryForm } from '#lib/entry-form/controller.svelte.js';
import { signedIn, written } from '#lib/entry-form/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import Page from '../../../routes/ledger/+page.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	listEntries: vi.fn(),
	listAccounts: vi.fn(),
	listCategories: vi.fn(),
	listPayees: vi.fn(),
	listTags: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));
vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/ledger') } }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('#lib/units/panel-instance.js', () => ({
	unitPanel: { open: vi.fn(), unitId: null, isOpen: false }
}));

beforeEach(() => {
	vi.resetAllMocks();
	lookupsStore.reset();
	signedIn();
	vi.mocked(api.listEntries).mockResolvedValue({ entries: [], total: 0 } as never);
	vi.mocked(api.listAccounts).mockResolvedValue([]);
	vi.mocked(api.listCategories).mockResolvedValue([]);
	vi.mocked(api.listPayees).mockResolvedValue([]);
	vi.mocked(api.listTags).mockResolvedValue([]);
});

describe('the ledger header: Add entry', () => {
	it('is the page header action, and opens the add form with the account filter', async () => {
		const openAdd = vi.spyOn(entryForm, 'openAdd');
		render(Page);

		const header = document.querySelector('[data-slot="page-header"]') as HTMLElement;
		await fireEvent.click(within(header).getByRole('button', { name: 'Add entry' }));

		expect(openAdd).toHaveBeenCalledWith({ filtered: [] });
		openAdd.mockRestore();
	});

	it('fetches the list again when an entry was entered, so the new row is there', async () => {
		render(Page);
		await waitFor(() => expect(api.listEntries).toHaveBeenCalledTimes(1));

		entryForm.created(written(), false);

		await waitFor(() => expect(api.listEntries).toHaveBeenCalledTimes(2));
	});

	it('shows what the entry form says on its notice line', async () => {
		render(Page);
		await waitFor(() => expect(api.listEntries).toHaveBeenCalled());

		entryForm.notify('Deleted entry −12.50 EUR.');

		expect(await screen.findByText('Deleted entry −12.50 EUR.')).toBeInTheDocument();
	});
});
