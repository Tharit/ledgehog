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
