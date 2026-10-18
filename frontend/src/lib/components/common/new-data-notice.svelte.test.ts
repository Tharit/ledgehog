import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import { changes } from '#lib/stores/changes.svelte.js';
import AccountsPage from '../../../routes/accounts/+page.svelte';
import NewDataNotice from './new-data-notice.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({ listAccounts: vi.fn(), readChanges: vi.fn() }));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));

const values = { ledger: 'b:1', documents: 'b:1', accounts: { '1': 'b:1' }, active_task: null };

/** a poll of the change watcher that finds these values */
async function poll(over: Partial<typeof values> = {}): Promise<void> {
	api.readChanges.mockResolvedValue({ ...values, ...over });
	await changes.read();
}

beforeEach(async () => {
	vi.resetAllMocks();
	api.readChanges.mockResolvedValue(values);
	changes.start();
	await changes.read();
});

afterEach(() => changes.stop());

describe('NewDataNotice', () => {
	it('says nothing, in its reserved line, while nothing is new', () => {
		render(NewDataNotice, { stale: false, onrefresh: () => {} });
		expect(screen.queryByText(/New data/)).toBeNull();
		expect(document.querySelector('[data-slot="notice-line"]')).not.toBeNull();
	});

	it('says "New data — Refresh" once, without a count, and Refresh asks for the refetch', async () => {
		const onrefresh = vi.fn();
		render(NewDataNotice, { stale: true, onrefresh });

		expect(screen.getByText('New data —')).toBeInTheDocument();
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
	it('fetches again when the ledger moves, in place, and not when only the documents or an account did', async () => {
		api.listAccounts.mockResolvedValue([account({ id: 1, name: 'Giro' })]);
		render(AccountsPage);
		await screen.findByText('Giro');
		expect(api.listAccounts).toHaveBeenCalledTimes(1);

		api.listAccounts.mockResolvedValue([
			account({ id: 1, name: 'Giro' }),
			account({ id: 2, name: 'Pocket' })
		]);
		await poll({ documents: 'b:2', accounts: { '1': 'b:2' } });
		await Promise.resolve();
		expect(api.listAccounts).toHaveBeenCalledTimes(1);

		await poll({ ledger: 'b:2' });
		await waitFor(() => expect(api.listAccounts).toHaveBeenCalledTimes(2));
		expect(await screen.findByText('Pocket')).toBeInTheDocument();
	});
});
