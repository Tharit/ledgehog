import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { accounts } from '#lib/accounts/controller.svelte.js';
import { cash, giro, loan, signedIn } from '#lib/entry-form/fixtures.js';
import { account } from '#lib/ledger/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { apiError } from '#lib/units/fixtures.js';
import AccountDialogs from './account-dialogs.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	createAccount: vi.fn(),
	listAccounts: vi.fn(),
	listCategories: vi.fn(),
	listPayees: vi.fn(),
	listTags: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));

async function open(options = {}) {
	render(AccountDialogs);
	accounts.openAdd(options);
	return await screen.findByRole('dialog', { name: 'Add account' });
}

const body = (): Record<string, unknown> => vi.mocked(api.createAccount).mock.calls[0][0];

beforeEach(() => {
	vi.resetAllMocks();
	accounts.close();
	lookupsStore.reset();
	signedIn([giro, cash, loan]);
	vi.mocked(api.listAccounts).mockResolvedValue([giro, cash, loan]);
	vi.mocked(api.listCategories).mockResolvedValue([]);
	vi.mocked(api.listPayees).mockResolvedValue([]);
	vi.mocked(api.listTags).mockResolvedValue([]);
});

describe('the Add account dialog', () => {
	it('has the title, the description, Name, Kind and Currency, and Cancel and Add', async () => {
		const dialog = await open();

		expect(
			within(dialog).getByText('Entered by hand. Transfers to it can be completed here.')
		).toBeInTheDocument();
		for (const label of ['Name', 'Kind', 'Currency', 'External reference'])
			expect(within(dialog).getByLabelText(label)).toBeInTheDocument();
		expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
		expect(within(dialog).getByRole('button', { name: 'Add' })).toBeDisabled();
	});

	it('preselects cash', async () => {
		const dialog = await open();

		expect(within(dialog).getByRole('button', { name: 'Kind' })).toHaveTextContent('Cash');
	});

	it('preselects the kind the caller gave', async () => {
		const dialog = await open({ kind: 'card' });

		expect(within(dialog).getByRole('button', { name: 'Kind' })).toHaveTextContent('Card');
	});

	it('shows a given currency as locked text, not a choice', async () => {
		const dialog = await open({ currency: 'USD' });

		const currency = within(dialog).getByLabelText('Currency');
		expect(currency).toHaveValue('USD');
		expect(currency).toHaveAttribute('readonly');
		expect(currency.tagName).toBe('INPUT');
	});

	it('lets the currency be chosen among the known ones when none is given', async () => {
		const dialog = await open();

		const currency = within(dialog).getByRole('button', { name: 'Currency' });
		expect(currency).toHaveTextContent('EUR');
		await fireEvent.click(currency);
		expect((await screen.findAllByRole('option')).map((o) => o.textContent?.trim())).toEqual([
			'EUR'
		]);
	});

	it('adds the account, puts it in the lookups, tells the caller and closes', async () => {
		const added = account({ id: 8, name: 'Cash USD', currency: 'USD' });
		vi.mocked(api.createAccount).mockResolvedValue({
			account: added,
			settle: { error: null, touched_entry_ids: [] }
		});
		const onadded = vi.fn();
		const dialog = await open({ currency: 'USD', onadded });

		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'Cash USD' } });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		await waitFor(() => expect(onadded).toHaveBeenCalledWith(added));
		expect(body()).toMatchObject({ name: 'Cash USD', kind: 'cash', currency: 'USD' });
		expect(lookupsStore.lookups.accounts.get(8)?.name).toBe('Cash USD');
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
	});

	it('sends the trimmed external reference and omits an empty one', async () => {
		vi.mocked(api.createAccount).mockResolvedValue({
			account: account({ id: 8 }),
			settle: { error: null, touched_entry_ids: [] }
		});
		const dialog = await open();
		const reference = within(dialog).getByLabelText('External reference');
		expect(reference).not.toHaveAttribute('placeholder');

		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'Visa' } });
		await fireEvent.input(reference, { target: { value: '  DE02 1234  ' } });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));
		await waitFor(() => expect(api.createAccount).toHaveBeenCalledTimes(1));
		expect(body()).toMatchObject({ external_ref: 'DE02 1234' });
	});

	it('omits a blank external reference', async () => {
		vi.mocked(api.createAccount).mockResolvedValue({
			account: account({ id: 8 }),
			settle: { error: null, touched_entry_ids: [] }
		});
		const dialog = await open();

		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'Wallet' } });
		await fireEvent.input(within(dialog).getByLabelText('External reference'), {
			target: { value: '   ' }
		});
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));
		await waitFor(() => expect(api.createAccount).toHaveBeenCalledTimes(1));
		expect(body()).not.toHaveProperty('external_ref');
	});

	it('says a duplicate external reference under that field', async () => {
		vi.mocked(api.createAccount).mockRejectedValue(
			apiError(409, 'conflict', { reason: 'duplicate_external_ref' })
		);
		const dialog = await open();

		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'Visa' } });
		await fireEvent.input(within(dialog).getByLabelText('External reference'), {
			target: { value: 'DE02' }
		});
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		expect(await within(dialog).findByRole('alert')).toHaveTextContent(/already uses/);
		expect(within(dialog).getByLabelText('External reference')).toHaveAttribute(
			'aria-invalid',
			'true'
		);
		expect(within(dialog).getByLabelText('Name')).not.toHaveAttribute('aria-invalid', 'true');
	});

	it('submits with Enter in the name field', async () => {
		vi.mocked(api.createAccount).mockResolvedValue({
			account: account({ id: 9 }),
			settle: { error: null, touched_entry_ids: [] }
		});
		const dialog = await open();

		const name = within(dialog).getByLabelText('Name');
		await fireEvent.input(name, { target: { value: 'Wallet' } });
		await fireEvent.submit(name.closest('form')!);

		await waitFor(() => expect(api.createAccount).toHaveBeenCalledTimes(1));
	});

	it('keeps the dialog open and says a refusal under the name', async () => {
		vi.mocked(api.createAccount).mockRejectedValue(apiError(422, 'validation_error'));
		const onadded = vi.fn();
		const dialog = await open({ onadded });

		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'a' } });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		expect(await within(dialog).findByRole('alert')).toHaveTextContent(/name/i);
		expect(within(dialog).getByLabelText('Name')).toHaveAttribute('aria-invalid', 'true');
		expect(onadded).not.toHaveBeenCalled();
		expect(screen.getByRole('dialog', { name: 'Add account' })).toBeInTheDocument();
	});

	it('says a failure that belongs to no field above the buttons', async () => {
		vi.mocked(api.createAccount).mockRejectedValue(apiError(0, 'network_error'));
		const dialog = await open();

		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'a' } });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		const feedback = await waitFor(() => {
			const el = dialog.querySelector('[data-slot="dialog-feedback"]');
			expect(el).not.toBeNull();
			return el!;
		});
		expect(feedback).toHaveTextContent(/could not be reached/);
	});

	it('closes on Cancel without adding', async () => {
		const dialog = await open();

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));

		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(api.createAccount).not.toHaveBeenCalled();
	});
});
