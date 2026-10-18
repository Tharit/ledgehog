import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import { sync } from '#lib/stores/sync.svelte.js';
import AccountsPage from '../../../routes/accounts/+page.svelte';
import NewDataNotice from './new-data-notice.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({ listAccounts: vi.fn() }));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));

beforeEach(() => vi.resetAllMocks());

describe('NewDataNotice', () => {
	it('says nothing, in its reserved line, while nothing is new', () => {
		render(NewDataNotice, { stale: false, onrefresh: () => {} });
		expect(screen.queryByText(/New data/)).toBeNull();
		expect(document.querySelector('[data-slot="notice-line"]')).not.toBeNull();
	});

	it('says "New data from a sync — Refresh" once, without a count, and Refresh asks for the refetch', async () => {
		const onrefresh = vi.fn();
		render(NewDataNotice, { stale: true, onrefresh });

		expect(screen.getByText('New data from a sync —')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
		expect(onrefresh).toHaveBeenCalledTimes(1);
	});

	it('gives way to the notice of a write', () => {
		render(NewDataNotice, {
			stale: true,
			onrefresh: () => {},
			notice: { text: 'Saved.', error: false }
		});
		expect(screen.getByText('Saved.')).toBeInTheDocument();
		expect(screen.queryByText(/New data/)).toBeNull();
		expect(screen.queryByRole('button', { name: 'Refresh' })).toBeNull();
	});
});

describe('the accounts list, which is not a snapshot', () => {
	it('fetches again when a sync ends, in place, and not when rows were merely written', async () => {
		api.listAccounts.mockResolvedValue([account({ id: 1, name: 'Giro' })]);
		render(AccountsPage);
		await screen.findByText('Giro');
		expect(api.listAccounts).toHaveBeenCalledTimes(1);

		api.listAccounts.mockResolvedValue([
			account({ id: 1, name: 'Giro' }),
			account({ id: 2, name: 'Pocket' })
		]);
		sync.dataRevision++;
		await Promise.resolve();
		expect(api.listAccounts).toHaveBeenCalledTimes(1);

		sync.endRevision++;
		await waitFor(() => expect(api.listAccounts).toHaveBeenCalledTimes(2));
		expect(await screen.findByText('Pocket')).toBeInTheDocument();
	});
});
