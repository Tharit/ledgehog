import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { catalogEntry, instance, link } from '#lib/importers/fixtures.js';
import { account } from '#lib/ledger/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { sync } from '#lib/stores/sync.svelte.js';
import InstanceEditorPage from './instance-editor-page.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	createInstance: vi.fn(),
	updateInstance: vi.fn(),
	listInstances: vi.fn(),
	listImporters: vi.fn(),
	linkAccount: vi.fn(),
	unlinkAccount: vi.fn()
}));
vi.mock('#lib/api/importers.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/importers.js')>()),
	...api
}));

const syncApi = vi.hoisted(() => ({ discoverAccounts: vi.fn() }));
vi.mock('#lib/api/sync.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/sync.js')>()),
	...syncApi
}));

type Navigation = { cancel: () => void; to: { url: URL } | null; willUnload: boolean };
const nav = vi.hoisted(() => ({
	callback: null as null | ((n: Navigation) => void),
	goto: vi.fn()
}));
vi.mock('$app/navigation', () => ({
	beforeNavigate: (callback: (n: Navigation) => void) => {
		nav.callback = callback;
	},
	goto: nav.goto
}));

const PRESET = {
	header_marker: ['Buchung', 'Betrag'],
	booked_on: 'Buchung',
	date_format: 'dd.MM.yyyy',
	amount: { column: 'Betrag', credit: null, debit: null }
};

beforeEach(() => {
	vi.resetAllMocks();
	nav.callback = null;
	lookupsStore.reset();
	lookupsStore.loaded = true;
	lookupsStore.setAccounts([
		account({ id: 7, name: 'Main giro' }),
		account({ id: 8, name: 'Old giro', closed_on: '2025-01-01' }),
		account({ id: 9, name: 'Savings' })
	]);
	api.listImporters.mockResolvedValue([catalogEntry({ presets: { giro: PRESET } })]);
	api.listInstances.mockResolvedValue([]);
});

async function adding() {
	const onleave = vi.fn();
	render(InstanceEditorPage, { props: { importer: 'csv', onleave } });
	await screen.findByRole('form', { name: 'Importer' });
	return onleave;
}

async function editing(
	over: Parameters<typeof instance>[0] = {},
	intent: 'added' | 'link' | null = null
) {
	api.listInstances.mockResolvedValue([
		instance({
			id: 4,
			label: 'Giro',
			settings: PRESET,
			accounts: [{ account_id: 7, external_ref: 'acct-7' }],
			...over
		})
	]);
	const onleave = vi.fn();
	const ontidy = vi.fn();
	render(InstanceEditorPage, { props: { instanceId: 4, intent, onleave, ontidy } });
	await screen.findByRole('form', { name: 'Importer' });
	return { onleave, ontidy };
}

describe('the instance page, adding', () => {
	it('is titled "Add importer" and offers a preset, a label and the profile form', async () => {
		await adding();

		expect(screen.getByRole('heading', { name: 'Add importer' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Start from a preset' })).toBeInTheDocument();
		expect(screen.getByLabelText('Label')).toBeInTheDocument();
		expect(screen.getByLabelText('Booking date column')).toBeInTheDocument();
		expect(screen.queryByText('Linked accounts')).toBeNull();
	});

	it('fills the form from a preset as a draft, and asks before it is thrown away', async () => {
		await adding();

		await fireEvent.click(screen.getByRole('button', { name: 'Start from a preset' }));
		await fireEvent.click(await screen.findByRole('option', { name: 'giro' }));

		expect(screen.getByLabelText('Booking date column')).toHaveValue('Buchung');
		expect(api.createInstance).not.toHaveBeenCalled();
		nav.callback!({
			cancel: vi.fn(),
			to: { url: new URL('http://localhost/settings/importers') },
			willUnload: false
		});
		expect(await screen.findByText('Discard changes?')).toBeInTheDocument();
		expect(
			screen.getByText('The changes to this importer have not been saved.')
		).toBeInTheDocument();
	});

	it('cannot be saved without a label, and says why', async () => {
		await adding();

		expect(screen.getByRole('button', { name: 'Save importer' })).toBeDisabled();
	});

	it('saves, then goes to the new instance’s page, which offers to link an account', async () => {
		api.createInstance.mockResolvedValue(instance({ id: 11, label: 'Giro' }));
		const onleave = await adding();
		await fireEvent.input(screen.getByLabelText('Label'), { target: { value: 'Giro' } });

		await fireEvent.click(screen.getByRole('button', { name: 'Save importer' }));

		await waitFor(() => expect(onleave).toHaveBeenCalledWith('/settings/importers/11?added=1'));
		expect(api.createInstance.mock.calls[0][0]).toBe('csv');
		expect(api.createInstance.mock.calls[0][1].label).toBe('Giro');
	});

	it('shows the server’s refusal of a setting under its field', async () => {
		const { ApiError } =
			await vi.importActual<typeof import('#lib/api/http.js')>('#lib/api/http.js');
		api.createInstance.mockRejectedValue(
			new ApiError(422, 'invalid_profile', 'date_format: unknown token', {
				setting: 'date_format'
			})
		);
		await adding();
		await fireEvent.input(screen.getByLabelText('Label'), { target: { value: 'Giro' } });

		await fireEvent.click(screen.getByRole('button', { name: 'Save importer' }));

		expect(await screen.findByText('Unknown token')).toBeInTheDocument();
		expect(screen.getByLabelText('Date format')).toHaveAttribute('aria-invalid', 'true');
	});
});

describe('the instance page, editing', () => {
	it('is titled with the label, holds the stored profile and lists the linked accounts', async () => {
		await editing();

		expect(screen.getByRole('heading', { name: 'Giro' })).toBeInTheDocument();
		expect(screen.getByLabelText('Booking date column')).toHaveValue('Buchung');
		expect(screen.queryByRole('button', { name: 'Start from a preset' })).toBeNull();
		expect(screen.getByRole('link', { name: 'Main giro' })).toHaveAttribute('href', '/accounts/7');
		expect(screen.getByRole('button', { name: 'Unlink Main giro' })).toBeInTheDocument();
	});

	it('saves and goes back to the list with the notice in the address', async () => {
		api.updateInstance.mockResolvedValue(instance({ id: 4, label: 'Giro 2' }));
		const { onleave } = await editing();
		await fireEvent.input(screen.getByLabelText('Label'), { target: { value: 'Giro 2' } });

		await fireEvent.click(screen.getByRole('button', { name: 'Save importer' }));

		await waitFor(() => expect(onleave).toHaveBeenCalled());
		expect(onleave.mock.calls[0][0]).toBe('/settings/importers?done=saved&label=Giro+2');
	});

	it('links an account: the picker offers open, unlinked accounts and shows the dry run', async () => {
		api.linkAccount.mockResolvedValueOnce(
			link({
				account_id: 9,
				user_authored_count: 14,
				first_booked_on: '2026-01-03',
				last_booked_on: '2026-03-29'
			})
		);
		await editing();

		await fireEvent.click(screen.getByRole('button', { name: 'Link account' }));
		await fireEvent.click(await screen.findByRole('button', { name: 'Account' }));
		expect(screen.queryByRole('option', { name: /Main giro/ })).toBeNull();
		expect(screen.queryByRole('option', { name: /Old giro/ })).toBeNull();
		await fireEvent.click(await screen.findByRole('option', { name: /Savings/ }));

		expect(
			await screen.findByText(/This account holds 14 rows entered by hand/)
		).toBeInTheDocument();
		expect(
			screen.getByText('Imports overlapping them are not deduplicated against them.')
		).toBeInTheDocument();
		expect(
			screen.getByText('Once linked, the account is synced: rows can no longer be entered by hand.')
		).toBeInTheDocument();
		expect(api.linkAccount).toHaveBeenCalledWith(4, 9, { dryRun: true });
	});

	it('opens the link dialog at once after a new instance was saved, and tidies the address', async () => {
		const { ontidy } = await editing({}, 'added');

		expect(await screen.findByRole('dialog')).toHaveTextContent('Link an account to “Giro”');
		expect(screen.getByText(/was added\. Link an account to use it\./)).toBeInTheDocument();
		expect(ontidy).toHaveBeenCalledOnce();
	});

	it('offers "Refresh accounts" instead of "Link account" for a fetch importer, which starts the discovery and opens its page', async () => {
		api.listImporters.mockResolvedValue([
			catalogEntry({ name: 'testfetch', kind: 'fetch', presets: {} })
		]);
		syncApi.discoverAccounts.mockResolvedValue({ task_id: 'd1' });
		vi.stubGlobal(
			'EventSource',
			class {
				readyState = 0;
				onerror = null;
				addEventListener() {}
				close() {}
			}
		);
		api.listInstances.mockResolvedValue([
			instance({ id: 4, label: 'Testbank', importer: 'testfetch', settings: {} })
		]);
		const onopen = vi.fn();
		render(InstanceEditorPage, {
			props: { instanceId: 4, onleave: vi.fn(), onopen }
		});
		await screen.findByRole('form', { name: 'Importer' });

		expect(screen.queryByRole('button', { name: 'Link account' })).toBeNull();
		await fireEvent.click(screen.getByRole('button', { name: 'Refresh accounts' }));

		await waitFor(() => expect(onopen).toHaveBeenCalledWith('/settings/importers/4/accounts'));
		expect(syncApi.discoverAccounts).toHaveBeenCalledWith(4);
		sync.dispose();
	});

	it('shows a refused start as a notice here, with a link to the running task when busy', async () => {
		const { ApiError } =
			await vi.importActual<typeof import('#lib/api/http.js')>('#lib/api/http.js');
		api.listImporters.mockResolvedValue([
			catalogEntry({ name: 'testfetch', kind: 'fetch', presets: {} })
		]);
		syncApi.discoverAccounts.mockRejectedValue(new ApiError(409, 'task_active', 'busy'));
		api.listInstances.mockResolvedValue([
			instance({ id: 4, label: 'Testbank', importer: 'testfetch', settings: {} })
		]);
		const onopen = vi.fn();
		render(InstanceEditorPage, { props: { instanceId: 4, onleave: vi.fn(), onopen } });
		await screen.findByRole('form', { name: 'Importer' });

		await fireEvent.click(screen.getByRole('button', { name: 'Refresh accounts' }));

		expect(await screen.findByText('A sync is already running')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Open the running task' })).toHaveAttribute(
			'href',
			'/sync'
		);
		expect(onopen).not.toHaveBeenCalled();
	});

	it('shows the FinTS form without the CSV copy, preset or label hint', async () => {
		api.listImporters.mockResolvedValue([
			catalogEntry({ name: 'fints', kind: 'fetch', presets: { odd: {} } })
		]);
		render(InstanceEditorPage, { props: { importer: 'fints', onleave: vi.fn() } });
		await screen.findByRole('form', { name: 'Importer' });

		expect(screen.getByLabelText('Bank address')).toBeInTheDocument();
		expect(screen.queryByText(/describe the file format/)).toBeNull();
		expect(screen.queryByText(/Start from a preset/)).toBeNull();
		expect(screen.queryByText(/say csv:/)).toBeNull();
		expect(screen.queryByText(/dry run/)).toBeNull();
	});

	it('keeps the CSV copy for csv', async () => {
		await adding();

		expect(screen.getByText(/describe the file format/)).toBeInTheDocument();
		expect(screen.getByText(/say csv:/)).toBeInTheDocument();
		expect(screen.getAllByText(/Start from a preset/).length).toBeGreaterThan(0);
	});

	it('unlinks after a decision that says the coverage stays', async () => {
		api.unlinkAccount.mockResolvedValue({ settle: { touched_entry_ids: [], error: null } });
		await editing();

		await fireEvent.click(screen.getByRole('button', { name: 'Unlink Main giro' }));
		const dialog = await screen.findByRole('dialog');
		expect(dialog).toHaveTextContent('coverage stays as history');
		await fireEvent.click(screen.getByRole('button', { name: 'Unlink' }));

		await waitFor(() => expect(api.unlinkAccount).toHaveBeenCalledWith(4, 7));
		expect(await screen.findByText('No account is linked yet.')).toBeInTheDocument();
	});
});

describe('the instance page, for an importer that delivers documents only', () => {
	async function editingEmail(intent: 'added' | null = null) {
		api.listImporters.mockResolvedValue([
			catalogEntry({ name: 'email', kind: 'fetch', emits: ['documents'], presets: {} })
		]);
		return editing(
			{ importer: 'email', emits: ['documents'], settings: {}, accounts: [], access: 'shared' },
			intent
		);
	}

	it('has no linked accounts section, only a line saying where its documents go', async () => {
		await editingEmail();

		expect(screen.queryByText('Linked accounts')).toBeNull();
		expect(screen.queryByRole('button', { name: 'Link account' })).toBeNull();
		expect(screen.queryByRole('button', { name: 'Refresh accounts' })).toBeNull();
		expect(
			screen.getByText(
				'What this importer delivers is booked onto the clearance account that takes each provider.'
			)
		).toBeInTheDocument();
	});

	it('says only that it was added, and opens no link dialog', async () => {
		await editingEmail('added');

		expect(screen.getByText('Importer “Giro” was added.')).toBeInTheDocument();
		expect(screen.queryByRole('dialog')).toBeNull();
	});
});

describe('the instance page, for the other user’s login', () => {
	const theirs = {
		access: 'owner' as const,
		owner_id: 2,
		owner_name: 'Ben',
		manageable: false
	};

	it('shows everything read-only: label, settings, whose login, accounts and last run', async () => {
		await editing(theirs);

		expect(screen.getByRole('heading', { name: 'Giro' })).toBeInTheDocument();
		expect(screen.getByLabelText('Label')).toHaveAttribute('readonly');
		expect(screen.getByLabelText('Booking date column')).toHaveValue('Buchung');
		expect(screen.getByLabelText('Booking date column')).toBeDisabled();
		expect(screen.getByText(/Ben’s login/)).toBeInTheDocument();
		expect(screen.getByText('never run')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Main giro' })).toBeInTheDocument();
		expect(screen.getByText(/only Ben can change it/)).toBeInTheDocument();
	});

	it('offers no editor and none of the actions', async () => {
		await editing(theirs);

		for (const name of ['Save importer', 'Cancel', 'Link account', 'Unlink Main giro']) {
			expect(screen.queryByRole('button', { name })).toBeNull();
		}
		expect(screen.queryByRole('link', { name: 'Cancel' })).toBeNull();
	});

	it('offers no "Refresh accounts" on a fetch importer', async () => {
		api.listImporters.mockResolvedValue([
			catalogEntry({ name: 'testfetch', kind: 'fetch', presets: {} })
		]);
		await editing({ ...theirs, importer: 'testfetch', settings: {} });

		expect(screen.queryByRole('button', { name: 'Refresh accounts' })).toBeNull();
	});

	it('does not open the link dialog on arrival, whatever the intent', async () => {
		await editing(theirs, 'link');

		expect(screen.queryByRole('dialog')).toBeNull();
	});

	it('keeps the editor for one’s own login', async () => {
		await editing({ ...theirs, owner_name: 'Anna', manageable: true });

		expect(screen.getByRole('button', { name: 'Save importer' })).toBeInTheDocument();
		expect(screen.queryByText(/only Anna can change it/)).toBeNull();
	});
});

describe('the instance page, adding an email importer', () => {
	async function addingEmail() {
		api.listImporters.mockResolvedValue([
			catalogEntry({
				name: 'email',
				kind: 'fetch',
				emits: ['documents'],
				presets: {}
			})
		]);
		const onleave = vi.fn();
		render(InstanceEditorPage, { props: { importer: 'email', onleave } });
		await screen.findByRole('form', { name: 'Importer' });
		return onleave;
	}

	async function fillIn() {
		await fireEvent.input(screen.getByLabelText('Label'), { target: { value: 'Receipts' } });
		await fireEvent.input(screen.getByLabelText('Mail server'), {
			target: { value: 'imap.example.org' }
		});
		await fireEvent.input(screen.getByLabelText('Login name'), { target: { value: 'me' } });
		await fireEvent.input(screen.getByLabelText('Senders'), {
			target: { value: 'Shop@Example.com' }
		});
	}

	it('prefills TLS, INBOX and today as the start date, and saves the settings', async () => {
		api.createInstance.mockResolvedValue(instance({ id: 12, importer: 'email' }));
		const onleave = await addingEmail();
		expect(screen.getByLabelText('Folder')).toHaveValue('INBOX');
		await fillIn();

		await fireEvent.click(screen.getByRole('button', { name: 'Save importer' }));

		await waitFor(() => expect(onleave).toHaveBeenCalled());
		expect(api.createInstance.mock.calls[0][0]).toBe('email');
		expect(api.createInstance.mock.calls[0][1].settings).toEqual({
			host: 'imap.example.org',
			security: 'tls',
			username: 'me',
			senders: ['shop@example.com'],
			start_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
			mailbox: 'INBOX'
		});
	});

	it('stops a save without a sender, on the field, before any request', async () => {
		await addingEmail();
		await fillIn();
		await fireEvent.input(screen.getByLabelText('Senders'), { target: { value: '' } });

		await fireEvent.click(screen.getByRole('button', { name: 'Save importer' }));

		expect(await screen.findByText('Enter at least one sender address.')).toBeInTheDocument();
		expect(api.createInstance).not.toHaveBeenCalled();
	});

	it('shows the server’s refusal of a setting under its field', async () => {
		const { ApiError } =
			await vi.importActual<typeof import('#lib/api/http.js')>('#lib/api/http.js');
		api.createInstance.mockRejectedValue(
			new ApiError(422, 'invalid_profile', 'port: must be a whole number from 1 to 65535', {
				setting: 'port'
			})
		);
		await addingEmail();
		await fillIn();

		await fireEvent.click(screen.getByRole('button', { name: 'Save importer' }));

		expect(await screen.findByText('Must be a whole number from 1 to 65535')).toBeInTheDocument();
		expect(screen.getByLabelText('Port')).toHaveAttribute('aria-invalid', 'true');
	});
});
