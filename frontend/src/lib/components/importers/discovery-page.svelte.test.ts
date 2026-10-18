import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { accounts as accountDialog } from '#lib/accounts/controller.svelte.js';
import { signedIn } from '#lib/entry-form/fixtures.js';
import { catalogEntry, discoveryEntry, instance, link } from '#lib/importers/fixtures.js';
import { account } from '#lib/ledger/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { sync } from '#lib/stores/sync.svelte.js';
import { foldAll, type TaskView } from '#lib/sync/events.js';
import { ev, instanceFailed, promptEvent, taskEnded, taskStarted } from '#lib/sync/fixtures.js';
import type { DiscoveryEntry } from '#lib/types/domain.js';
import Harness from './discovery-page.harness.svelte';

// components never import the API, not even in tests: the mocks come from here
const importersApi = vi.hoisted(() => ({
	listInstances: vi.fn(),
	listImporters: vi.fn(),
	linkAccount: vi.fn()
}));
vi.mock('#lib/api/importers.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/importers.js')>()),
	...importersApi
}));
const syncApi = vi.hoisted(() => ({
	discoverAccounts: vi.fn(),
	getTaskStatus: vi.fn(),
	answerPrompt: vi.fn()
}));
vi.mock('#lib/api/sync.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/sync.js')>()),
	...syncApi
}));
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

const testbank = instance({ id: 4, label: 'Testbank', importer: 'testfetch', settings: {} });
const catalog = [catalogEntry({ name: 'testfetch', kind: 'fetch', presets: {} })];
const savings = account({ id: 9, name: 'Savings', currency: 'EUR' });
const old = account({ id: 8, name: 'Old giro', closed_on: '2025-01-01' });

const entries = (): DiscoveryEntry[] => [
	discoveryEntry({ name: 'Linked one', external_ref: 'R1', linked_account_id: 7 }),
	discoveryEntry({ name: 'Testbank Depot', external_ref: 'R2', capabilities: [] }),
	discoveryEntry({
		name: 'Closed one',
		external_ref: 'R3',
		matches_account: { id: 8, closed: true }
	}),
	discoveryEntry({
		name: 'Savings pocket',
		external_ref: 'R4',
		kind_hint: 'savings',
		matches_account: { id: 9, closed: false }
	}),
	discoveryEntry({ name: 'Testbank Dollars', external_ref: 'R5', currency: 'USD' })
];

const status = (result: DiscoveryEntry[] | null) => ({
	task_id: 'd1',
	kind: 'discovery' as const,
	status: 'ended' as const,
	aborting: false,
	outcome: 'completed' as const,
	last_event_id: 3,
	result: result ? { instance_id: 4, accounts: result } : null
});

function view(...events: ReturnType<typeof ev>[]): TaskView {
	return foldAll([
		ev(1, 'task_started', taskStarted([{ id: 4, accounts: [] }], 'discovery')),
		...events
	]);
}

function hold(taskView: TaskView, phase: 'running' | 'ended') {
	sync.kind = 'discovery';
	sync.taskId = 'd1';
	sync.view = taskView;
	sync.status = phase;
}

function mount() {
	return render(Harness, { props: { instanceId: 4 } });
}

beforeEach(() => {
	vi.resetAllMocks();
	vi.stubGlobal(
		'EventSource',
		class {
			readyState = 0;
			onerror = null;
			addEventListener() {}
			close() {}
		}
	);
	sync.dispose();
	accountDialog.close();
	lookupsStore.reset();
	signedIn([savings, old, account({ id: 7, name: 'Giro' })]);
	importersApi.listInstances.mockResolvedValue([testbank]);
	importersApi.listImporters.mockResolvedValue(catalog);
	api.listAccounts.mockResolvedValue([savings, old, account({ id: 7, name: 'Giro' })]);
	api.listCategories.mockResolvedValue([]);
	api.listPayees.mockResolvedValue([]);
	api.listTags.mockResolvedValue([]);
});

describe('the Refresh accounts page, running', () => {
	it('says it is looking, and asks the PIN in the prompt dialog that was open before this page was shown', async () => {
		hold(
			view(ev(2, 'instance_started', { instance_id: 4 }), ev(3, 'prompt', promptEvent(4, null))),
			'running'
		);

		mount();

		expect(await screen.findByText('Looking up the accounts of Testbank…')).toBeInTheDocument();
		const dialog = await screen.findByRole('dialog', { name: 'PIN for Testbank' });
		expect(within(dialog).getByText('Signing in.')).toBeInTheDocument();
		// a discovery's prompt has no "Stop sync…"
		expect(within(dialog).queryByRole('button', { name: /Stop sync/ })).toBeNull();

		await fireEvent.input(within(dialog).getByLabelText('PIN'), { target: { value: '1234' } });
		syncApi.answerPrompt.mockResolvedValue(undefined);
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Sign in' }));
		await waitFor(() =>
			expect(syncApi.answerPrompt).toHaveBeenCalledWith('d1', { prompt_id: 'p1', value: '1234' })
		);
	});

	it('has the title and the description', async () => {
		hold(view(), 'running');
		mount();

		expect(await screen.findByRole('heading', { name: 'Refresh accounts' })).toBeInTheDocument();
		expect(
			await screen.findByText('What Testbank can reach at the bank, and what each is here.')
		).toBeInTheDocument();
	});
});

describe('the Refresh accounts page, ended', () => {
	async function ended(result: DiscoveryEntry[] = entries()) {
		syncApi.getTaskStatus.mockResolvedValue(status(result));
		hold(view(ev(2, 'task_ended', taskEnded({ ok: 0 }))), 'ended');
		mount();
		await screen.findByText('Testbank Dollars');
	}

	it('reads the result and shows one row per account, each in its state, in the order given', async () => {
		await ended();

		const rows = [...document.querySelectorAll('[data-slot="discovery-rows"] li')];
		expect(rows.map((r) => r.getAttribute('data-state'))).toEqual([
			'linked',
			'nothing_to_fetch',
			'closed',
			'match',
			'new'
		]);
		expect(syncApi.getTaskStatus).toHaveBeenCalledWith('d1');
		expect(within(rows[0] as HTMLElement).getByRole('link', { name: 'Giro' })).toHaveAttribute(
			'href',
			'/accounts/7'
		);
		expect(
			within(rows[1] as HTMLElement).getByText(
				'The bank offers neither bookings nor a balance for this account.'
			)
		).toBeInTheDocument();
		// a closed account's match is not offered
		expect(within(rows[2] as HTMLElement).queryByRole('button')).toBeNull();
		expect(
			within(rows[3] as HTMLElement).getByRole('button', { name: 'Link Savings pocket' })
		).toBeInTheDocument();
		expect(
			within(rows[4] as HTMLElement).getByRole('button', { name: 'Add and link Testbank Dollars' })
		).toBeInTheDocument();
		// the reference as the bank reports it
		expect(within(rows[4] as HTMLElement).getByText('R5')).toBeInTheDocument();
	});

	it('links with "Link…": the account is fixed, the dry run shown, the discovered reference sent; the row changes in place and a notice offers Fetch', async () => {
		importersApi.linkAccount
			.mockResolvedValueOnce(
				link({
					account_id: 9,
					external_ref: 'R4',
					user_authored_count: 14,
					first_booked_on: '2026-01-03',
					last_booked_on: '2026-03-29'
				})
			)
			.mockResolvedValueOnce(link({ account_id: 9, external_ref: 'R4', dry_run: false }));
		await ended();

		await fireEvent.click(screen.getByRole('button', { name: 'Link Savings pocket' }));

		const dialog = await screen.findByRole('dialog', { name: /Link an account to “Testbank”/ });
		expect(within(dialog).getByLabelText('Account')).toHaveValue('Savings');
		expect(
			await within(dialog).findByText(/This account holds 14 rows entered by hand/)
		).toBeInTheDocument();
		expect(importersApi.linkAccount).toHaveBeenCalledWith(4, 9, {
			dryRun: true,
			externalRef: 'R4'
		});

		// what the server answers when the status is read again
		syncApi.getTaskStatus.mockResolvedValue(
			status(
				entries().map((e) => (e.account.external_ref === 'R4' ? { ...e, linked_account_id: 9 } : e))
			)
		);
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Link' }));

		await waitFor(() =>
			expect(importersApi.linkAccount).toHaveBeenLastCalledWith(4, 9, { externalRef: 'R4' })
		);
		await waitFor(() => expect(document.querySelectorAll('[data-state="linked"]')).toHaveLength(2));
		const rows = [...document.querySelectorAll('[data-slot="discovery-rows"] li')];
		expect(rows.map((r) => r.getAttribute('data-state'))).toEqual([
			'linked',
			'nothing_to_fetch',
			'closed',
			'linked',
			'new'
		]);
		expect(await screen.findByRole('link', { name: 'Fetch' })).toHaveAttribute(
			'href',
			'/sync?instance=4'
		);
	});

	it('adds and links in one dialog: the add dialog is prefilled, adding then links at once, with no second dialog', async () => {
		const added = account({ id: 21, name: 'Testbank Dollars', currency: 'USD', kind: 'checking' });
		api.createAccount.mockResolvedValue({
			account: added,
			settle: { error: null, touched_entry_ids: [] }
		});
		importersApi.linkAccount.mockResolvedValue(
			link({ account_id: 21, external_ref: 'R5', dry_run: false })
		);
		await ended();

		await fireEvent.click(screen.getByRole('button', { name: 'Add and link Testbank Dollars' }));

		const dialog = await screen.findByRole('dialog', { name: 'Add account' });
		expect(within(dialog).getByLabelText('Name')).toHaveValue('Testbank Dollars');
		expect(within(dialog).getByRole('button', { name: 'Kind' })).toHaveTextContent('Checking');
		expect(within(dialog).getByLabelText('Currency')).toHaveValue('USD');
		expect(within(dialog).getByLabelText('External reference')).toHaveValue('R5');

		syncApi.getTaskStatus.mockResolvedValue(
			status(
				entries().map((e) =>
					e.account.external_ref === 'R5' ? { ...e, linked_account_id: 21 } : e
				)
			)
		);
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add and link' }));

		await waitFor(() =>
			expect(api.createAccount).toHaveBeenCalledWith(
				expect.objectContaining({
					name: 'Testbank Dollars',
					kind: 'checking',
					currency: 'USD',
					external_ref: 'R5'
				})
			)
		);
		await waitFor(() =>
			expect(importersApi.linkAccount).toHaveBeenCalledWith(4, 21, { externalRef: 'R5' })
		);
		// the link was not previewed: a new account holds no rows to warn about
		expect(importersApi.linkAccount).toHaveBeenCalledTimes(1);
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		await waitFor(() => expect(document.querySelector('[data-state="new"]')).toBeNull());
		expect(await screen.findByRole('link', { name: 'Fetch' })).toBeInTheDocument();
	});

	it('says so when the account was added but the link failed, and reads the row again so it offers "Link…"', async () => {
		const { ApiError } =
			await vi.importActual<typeof import('#lib/api/http.js')>('#lib/api/http.js');
		api.createAccount.mockResolvedValue({
			account: account({ id: 21, name: 'Testbank Dollars', currency: 'USD' }),
			settle: { error: null, touched_entry_ids: [] }
		});
		importersApi.linkAccount.mockRejectedValue(new ApiError(409, 'already_linked', 'x'));
		await ended();
		await fireEvent.click(screen.getByRole('button', { name: 'Add and link Testbank Dollars' }));
		const dialog = await screen.findByRole('dialog', { name: 'Add account' });
		syncApi.getTaskStatus.mockResolvedValue(
			status(
				entries().map((e) =>
					e.account.external_ref === 'R5' ? { ...e, matches_account: { id: 21, closed: false } } : e
				)
			)
		);

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add and link' }));

		expect(
			await screen.findByText(/Testbank Dollars was added, but linking it failed/)
		).toBeInTheDocument();
		await waitFor(() =>
			expect(screen.getByRole('button', { name: 'Link Testbank Dollars' })).toBeInTheDocument()
		);
		expect(screen.queryByRole('link', { name: 'Fetch' })).toBeNull();
	});

	it('says that the login reaches no accounts when the list is empty', async () => {
		syncApi.getTaskStatus.mockResolvedValue(status([]));
		hold(view(ev(2, 'task_ended', taskEnded())), 'ended');
		mount();

		expect(
			await screen.findByText('Testbank reaches no accounts at the bank.')
		).toBeInTheDocument();
	});
});

describe('the Refresh accounts page, failed', () => {
	it('shows the failure of the login, and "Try again" restarts the discovery when trying again can help', async () => {
		syncApi.getTaskStatus.mockResolvedValue(status(null));
		syncApi.discoverAccounts.mockResolvedValue({ task_id: 'd2' });
		hold(
			view(
				ev(
					2,
					'instance_failed',
					instanceFailed(4, { retryable: true, message: 'WrongPin: the PIN was refused' })
				),
				ev(3, 'task_ended', taskEnded({ failed: 1 }))
			),
			'ended'
		);
		mount();

		expect(await screen.findByText('WrongPin: the PIN was refused')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));

		await waitFor(() => expect(syncApi.discoverAccounts).toHaveBeenCalledWith(4));
		expect(await screen.findByText('Looking up the accounts of Testbank…')).toBeInTheDocument();
	});

	it('says what to fix, with a link to the login, when trying again will not help', async () => {
		syncApi.getTaskStatus.mockResolvedValue(status(null));
		hold(
			view(
				ev(
					2,
					'instance_failed',
					instanceFailed(4, { retryable: false, message: 'LoginLocked: the login is locked' })
				),
				ev(3, 'task_ended', taskEnded({ failed: 1 }))
			),
			'ended'
		);
		mount();

		expect(await screen.findByText('LoginLocked: the login is locked')).toBeInTheDocument();
		expect(screen.getByText(/Trying again will not help yet/)).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
		expect(screen.getByRole('link', { name: "Open the login's settings" })).toHaveAttribute(
			'href',
			'/settings/importers/4'
		);
	});
});

describe('the Refresh accounts page, reached with no task', () => {
	it('says one sentence and offers "Refresh accounts", which starts the discovery', async () => {
		syncApi.discoverAccounts.mockResolvedValue({ task_id: 'd1' });
		mount();

		expect(
			await screen.findByText('Ask the bank which accounts Testbank can reach.')
		).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Refresh accounts' }));

		await waitFor(() => expect(syncApi.discoverAccounts).toHaveBeenCalledWith(4));
		expect(await screen.findByText('Looking up the accounts of Testbank…')).toBeInTheDocument();
	});

	it('shows a refused start as a notice, a busy one with a link to the running task', async () => {
		const { ApiError } =
			await vi.importActual<typeof import('#lib/api/http.js')>('#lib/api/http.js');
		syncApi.discoverAccounts.mockRejectedValue(new ApiError(409, 'task_active', 'busy'));
		mount();
		await fireEvent.click(await screen.findByRole('button', { name: 'Refresh accounts' }));

		expect(await screen.findByText('A sync is already running')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Open the running task' })).toHaveAttribute(
			'href',
			'/sync'
		);
	});
});
