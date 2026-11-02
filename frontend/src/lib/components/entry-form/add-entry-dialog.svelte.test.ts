import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { formatDate, todayIso } from '#lib/format/index.js';
import { entryForm } from '#lib/entry-form/controller.svelte.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { apiError } from '#lib/units/fixtures.js';
import AddEntryDialog from './add-entry-dialog.svelte';
import { cash, giro, loan, signedIn, written } from '#lib/entry-form/fixtures.js';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	createSource: vi.fn(),
	listAccounts: vi.fn(),
	listCategories: vi.fn(),
	listPayees: vi.fn(),
	listTags: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));
const panel = vi.hoisted(() => ({
	open: vi.fn(),
	close: vi.fn(),
	retry: vi.fn(),
	reload: vi.fn(),
	isOpen: false,
	unit: null,
	unitId: null
}));
vi.mock('#lib/units/panel-instance.js', () => ({ unitPanel: panel }));

const today = todayIso('UTC');

async function open(props: Record<string, unknown> = {}) {
	const onclose = vi.fn();
	render(AddEntryDialog, { props: { open: true, onclose, ...props } });
	const dialog = await screen.findByRole('dialog', { name: 'Add entry' });
	return { dialog, onclose };
}

const field = (dialog: HTMLElement, label: string) =>
	within(dialog).getByLabelText(label) as HTMLInputElement;

// the account and date controls are buttons that open a popover
const account = (dialog: HTMLElement) => within(dialog).getByRole('button', { name: 'Account' });
const date = (dialog: HTMLElement) => within(dialog).getByRole('button', { name: 'Date' });

async function chooseAccount(dialog: HTMLElement, name: string) {
	await fireEvent.click(account(dialog));
	await fireEvent.click(await screen.findByRole('option', { name: new RegExp(name) }));
}

async function chooseDay(dialog: HTMLElement, iso: string) {
	await fireEvent.click(date(dialog));
	const day = await waitFor(() => {
		const found = document.querySelector(`[data-bits-day][data-value="${iso}"]`);
		expect(found).not.toBeNull();
		return found as HTMLElement;
	});
	await fireEvent.click(day);
}

async function fill(dialog: HTMLElement, amount: string, purpose = '') {
	await fireEvent.input(field(dialog, 'Amount'), { target: { value: amount } });
	if (purpose) await fireEvent.input(field(dialog, 'Purpose'), { target: { value: purpose } });
}

function body(call = 0): Record<string, unknown> {
	return vi.mocked(api.createSource).mock.calls[call][0] as Record<string, unknown>;
}

beforeEach(() => {
	// jsdom has no ResizeObserver, which the popover's positioning looks for
	vi.stubGlobal(
		'ResizeObserver',
		class {
			observe() {}
			unobserve() {}
			disconnect() {}
		}
	);
	vi.resetAllMocks();
	panel.isOpen = false;
	lookupsStore.reset();
	signedIn();
	vi.mocked(api.listAccounts).mockResolvedValue([giro, cash, loan]);
	vi.mocked(api.listCategories).mockResolvedValue([]);
	vi.mocked(api.listPayees).mockResolvedValue([]);
	vi.mocked(api.listTags).mockResolvedValue([]);
	// a plain store of our own: the environment's may be absent or shared
	const kept = new Map<string, string>();
	vi.stubGlobal('localStorage', {
		getItem: (key: string) => kept.get(key) ?? null,
		setItem: (key: string, value: string) => void kept.set(key, value)
	});
});

describe('AddEntryDialog: the form', () => {
	it('has account, date, amount with its sign and purpose, and Cancel, "Add and add another", Add', async () => {
		const { dialog } = await open();

		for (const label of ['Account', 'Date', 'Amount', 'Purpose']) {
			expect(within(dialog).getByLabelText(label)).toBeInTheDocument();
		}
		expect(within(dialog).queryByRole('radio')).toBeNull();
		expect(field(dialog, 'Amount').value).toBe('\u2212');
		const hint = within(dialog).getByText('\u2212 money out, + money in');
		expect(field(dialog, 'Amount').getAttribute('aria-describedby')).toContain(hint.id);
		const buttons = within(dialog)
			.getAllByRole('button')
			.map((b) => b.textContent?.trim());
		expect(
			buttons.filter((b) => ['Cancel', 'Add and add another', 'Add'].includes(b ?? ''))
		).toEqual(['Cancel', 'Add and add another', 'Add']);
	});

	it('offers only accounts without a bank connection', async () => {
		const { dialog } = await open();

		await fireEvent.click(account(dialog));
		const options = await screen.findAllByRole('option');
		expect(options.map((o) => o.textContent?.trim())).toEqual(['Cash', 'Hand loan']);
	});

	it('starts on today, and on the account the ledger is filtered to when it is exactly one', async () => {
		const { dialog } = await open({ options: { filtered: [3] } });

		expect(date(dialog)).toHaveTextContent(formatDate(today));
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Hand loan'));
	});

	it('starts on the last account used', async () => {
		localStorage.setItem('ledgehog.entry-form.account.1', '3');
		const { dialog } = await open();

		await waitFor(() => expect(account(dialog)).toHaveTextContent('Hand loan'));
	});

	it('explains, and cannot add, when every account has a bank connection', async () => {
		signedIn([giro]);
		const { dialog } = await open();

		expect(
			within(dialog).getByText(
				'Entries are added by hand only on accounts without a bank connection.'
			)
		).toBeInTheDocument();
		expect(within(dialog).getByRole('button', { name: 'Add' })).toBeDisabled();
		expect(within(dialog).getByRole('button', { name: 'Add and add another' })).toBeDisabled();
	});

	it('keeps no draft: closed and opened again, the form is empty', async () => {
		const onclose = vi.fn();
		const view = render(AddEntryDialog, { props: { open: true, onclose } });
		const dialog = await screen.findByRole('dialog', { name: 'Add entry' });
		await fill(dialog, '\u221212.50', 'groceries');

		await view.rerender({ open: false, onclose });
		await view.rerender({ open: true, onclose });

		const again = await screen.findByRole('dialog', { name: 'Add entry' });
		expect(field(again, 'Amount').value).toBe('\u2212');
		expect(field(again, 'Purpose').value).toBe('');
	});
});

describe('AddEntryDialog: account and date controls', () => {
	it('chooses an account from the popover with the find box, and closes it', async () => {
		signedIn([giro, loan, { ...loan, id: 9, name: 'Other loan' }]);
		const { dialog } = await open();

		await fireEvent.click(account(dialog));
		await fireEvent.input(await screen.findByLabelText('Search account'), {
			target: { value: 'other' }
		});
		expect(screen.queryByRole('option', { name: /Hand loan/ })).toBeNull();
		await fireEvent.click(screen.getByRole('option', { name: /Other loan/ }));

		expect(account(dialog)).toHaveTextContent('Other loan');
		await waitFor(() => expect(screen.queryByRole('option')).toBeNull());
	});

	it('clears the account error when an account is chosen', async () => {
		signedIn([giro, loan, { ...loan, id: 9, name: 'Other loan' }]);
		const { dialog } = await open();
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));
		await within(dialog).findByText('Choose an account.');

		await chooseAccount(dialog, 'Hand loan');

		expect(within(dialog).queryByText('Choose an account.')).toBeNull();
	});

	it('chooses a day in the calendar: the date changes and the popover closes', async () => {
		vi.mocked(api.createSource).mockResolvedValue(written());
		const { dialog } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));

		await chooseDay(dialog, today.slice(0, 8) + '01');
		expect(date(dialog)).toHaveTextContent(formatDate(today.slice(0, 8) + '01'));
		await waitFor(() => expect(document.querySelector('[data-bits-day]')).toBeNull());
		await fill(dialog, '\u22125');
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		await waitFor(() => expect(api.createSource).toHaveBeenCalled());
		expect(body()).toMatchObject({ booked_on: today.slice(0, 8) + '01' });
	});
});

describe('AddEntryDialog: Add', () => {
	it('enters the transaction with a signed amount, and closes without opening the panel', async () => {
		vi.mocked(api.createSource).mockResolvedValue(written({ anchor_entry_id: 77 }));
		const created = vi.fn();
		const stop = entryForm.listen({ created });
		const { dialog, onclose } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));
		await fill(dialog, '\u221212.50', ' groceries ');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		await waitFor(() => expect(onclose).toHaveBeenCalledOnce());
		expect(body()).toMatchObject({
			account_id: 1,
			amount: -1250,
			booked_on: today,
			purpose: 'groceries'
		});
		expect(body().id).toMatch(/^[A-Za-z0-9_-]{1,100}$/);
		expect(panel.open).not.toHaveBeenCalled();
		expect(created).toHaveBeenCalledOnce();
		stop();
	});

	it('enters an income with a positive amount', async () => {
		vi.mocked(api.createSource).mockResolvedValue(written());
		const { dialog } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));
		await fill(dialog, '+40');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		await waitFor(() => expect(api.createSource).toHaveBeenCalled());
		expect(body()).toMatchObject({ amount: 4000, purpose: null });
	});

	it('submits from Enter in a field: the form is submitted', async () => {
		vi.mocked(api.createSource).mockResolvedValue(written());
		const { dialog } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));
		await fill(dialog, '\u22125');

		await fireEvent.submit(field(dialog, 'Purpose').closest('form') as HTMLFormElement);

		await waitFor(() => expect(api.createSource).toHaveBeenCalledOnce());
	});

	it('says what is missing under the field and sends nothing', async () => {
		// no cash account to start on: the user has to choose
		signedIn([giro, loan, { ...loan, id: 9, name: 'Other loan' }]);
		const { dialog } = await open();

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		expect(await within(dialog).findByText('Choose an account.')).toBeInTheDocument();
		expect(within(dialog).getByText('Enter an amount.')).toBeInTheDocument();
		expect(api.createSource).not.toHaveBeenCalled();
	});

	it('asks for a sign when there is none, and sends nothing', async () => {
		const { dialog } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));
		await fill(dialog, '12.50');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		expect(
			await within(dialog).findByText('Add a sign: \u2212 for money out, + for money in')
		).toBeInTheDocument();
		expect(api.createSource).not.toHaveBeenCalled();
	});

	it('refuses the sign alone as no amount', async () => {
		const { dialog } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		expect(await within(dialog).findByText('Enter an amount.')).toBeInTheDocument();
		expect(api.createSource).not.toHaveBeenCalled();
	});

	it('refuses an ambiguous amount instead of guessing', async () => {
		const { dialog } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));
		await fill(dialog, '\u22121,234');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		expect(await within(dialog).findByText(/two ways/)).toBeInTheDocument();
		expect(api.createSource).not.toHaveBeenCalled();
	});
});

describe('AddEntryDialog: Add and add another', () => {
	it('keeps the dialog, resets the amount to its sign and clears the purpose, keeps account, date and sign, and says what was added', async () => {
		vi.mocked(api.createSource).mockResolvedValue(written());
		const { dialog, onclose } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));
		const day = today.slice(0, 8) + '01';
		await chooseDay(dialog, day);
		await fill(dialog, '+12.50', 'refund');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add and add another' }));

		expect(await within(dialog).findByText(/^Added .*12\.50.*EUR · refund\.$/)).toBeInTheDocument();
		expect(field(dialog, 'Amount').value).toBe('+');
		expect(field(dialog, 'Purpose').value).toBe('');
		expect(account(dialog)).toHaveTextContent('Cash');
		expect(date(dialog)).toHaveTextContent(formatDate(day));
		await waitFor(() => expect(field(dialog, 'Amount')).toHaveFocus());
		expect(field(dialog, 'Amount').selectionStart).toBe(1);
		expect(onclose).not.toHaveBeenCalled();
		expect(panel.open).not.toHaveBeenCalled();
		expect(body()).toMatchObject({ amount: 1250, booked_on: day });
	});

	it('enters the next one with a new id', async () => {
		vi.mocked(api.createSource).mockResolvedValue(written());
		const { dialog } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));
		await fill(dialog, '\u22125');
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add and add another' }));
		await within(dialog).findByText(/^Added/);

		await fill(dialog, '\u22125');
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add and add another' }));

		await waitFor(() => expect(api.createSource).toHaveBeenCalledTimes(2));
		expect(body(1).id).not.toBe(body(0).id);
	});
});

describe('AddEntryDialog: idempotency and failures', () => {
	it('retries with the same id while the values are unchanged, and with a new one after a change', async () => {
		vi.mocked(api.createSource)
			.mockRejectedValueOnce(apiError(0, 'network_error'))
			.mockRejectedValueOnce(apiError(0, 'network_error'))
			.mockResolvedValue(written());
		const { dialog } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));
		await fill(dialog, '\u221212.50');
		const add = () => fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		await add();
		await waitFor(() => expect(api.createSource).toHaveBeenCalledTimes(1));
		await within(dialog).findByRole('alert');
		await add();
		await waitFor(() => expect(api.createSource).toHaveBeenCalledTimes(2));
		await within(dialog).findByRole('alert');
		await fill(dialog, '\u221213');
		await add();
		await waitFor(() => expect(api.createSource).toHaveBeenCalledTimes(3));

		expect(body(1).id).toBe(body(0).id);
		expect(body(2).id).not.toBe(body(0).id);
	});

	it('says a lost connection in the dialog, with Try again, and keeps the dialog open and filled', async () => {
		vi.mocked(api.createSource).mockRejectedValue(apiError(0, 'network_error'));
		const { dialog, onclose } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));
		await fill(dialog, '\u221212.50');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		expect(await within(dialog).findByText(/could not be reached/)).toBeInTheDocument();
		expect(within(dialog).getByRole('button', { name: 'Try again' })).toBeInTheDocument();
		expect(field(dialog, 'Amount').value).toBe('\u221212.50');
		expect(onclose).not.toHaveBeenCalled();
	});

	it('puts account_synced under Account', async () => {
		vi.mocked(api.createSource).mockRejectedValue(apiError(422, 'account_synced'));
		const { dialog } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));
		await fill(dialog, '\u221212.50');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		expect(
			await within(dialog).findByText(
				'Entries are added by hand only on accounts without a bank connection.'
			)
		).toBeInTheDocument();
	});

	it('puts a stale account under Account and reloads the lists', async () => {
		vi.mocked(api.createSource).mockRejectedValue(
			Object.assign(apiError(409, 'stale_reference'), { details: { field: 'account_id' } })
		);
		vi.mocked(api.listAccounts).mockResolvedValue([giro, loan]);
		const { dialog } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));
		await fill(dialog, '\u221212.50');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		expect(await within(dialog).findByText(/no longer exists/)).toBeInTheDocument();
		await waitFor(() => expect(api.listAccounts).toHaveBeenCalled());
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Choose an account…'));
	});

	it('puts a server validation error under the field it names', async () => {
		vi.mocked(api.createSource).mockRejectedValue(
			Object.assign(apiError(422, 'validation_error'), {
				details: [{ location: ['body', 'purpose'], message: 'too long for the server', type: 'x' }]
			})
		);
		const { dialog } = await open({ options: { filtered: [1] } });
		await waitFor(() => expect(account(dialog)).toHaveTextContent('Cash'));
		await fill(dialog, '\u221212.50');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		expect(await within(dialog).findByText('too long for the server')).toBeInTheDocument();
	});
});
