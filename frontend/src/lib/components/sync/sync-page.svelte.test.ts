import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
/* eslint-disable no-restricted-imports -- the test stubs the API at its boundary */
import { ApiError } from '#lib/api/index.js';
/* eslint-enable no-restricted-imports */
import { account } from '#lib/ledger/fixtures.js';
import { foldAll, type TaskView } from '#lib/sync/events.js';
import {
	ev,
	instanceFailed,
	planInstance,
	promptEvent,
	runFinished,
	runStarted,
	taskEnded,
	taskStarted
} from '#lib/sync/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { sync } from '#lib/stores/sync.svelte.js';
import Page from '../../../routes/sync/+page.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	readSyncPlan: vi.fn(),
	startSync: vi.fn(),
	answerPrompt: vi.fn(),
	abortTask: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));
// the page is arrived at with the address in `arrival.search`; afterNavigate fires on mount like the real one
const arrival = vi.hoisted(() => ({ search: '' }));
vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/sync') } }));
vi.mock('$app/navigation', () => ({
	afterNavigate: (callback: (navigation: unknown) => void) =>
		callback({ to: { url: new URL(`http://localhost/sync${arrival.search}`) } })
}));

const accounts = [account({ id: 7, name: 'Giro' }), account({ id: 8, name: 'Pocket' })];
const plan = [
	planInstance({
		instance_id: 1,
		label: 'Giro login',
		accounts: [
			{
				account_id: 7,
				external_ref: 'r7',
				since: '2026-10-08',
				since_source: 'coverage',
				editable: false
			},
			{
				account_id: 8,
				external_ref: 'r8',
				since: '2026-01-01',
				since_source: 'importer_default',
				editable: true
			}
		],
		documents_since: '2026-03-01'
	}),
	planInstance({ instance_id: 2, label: 'Card login', busy: true })
];

/** a view of the task as the store would hold it after a replay */
function replayed(): TaskView {
	return foldAll([
		ev(1, 'task_started', taskStarted([{ id: 1, accounts: [7, 8] }])),
		ev(2, 'instance_started', { instance_id: 1 })
	]);
}

function hold(view: TaskView, status: 'running' | 'ended' = 'running') {
	sync.kind = 'sync';
	sync.taskId = 't1';
	sync.view = view;
	sync.status = status;
}

beforeEach(() => {
	vi.resetAllMocks();
	// a started task attaches to its stream; jsdom has no EventSource
	vi.stubGlobal(
		'EventSource',
		class {
			readyState = 0;
			onerror = null;
			addEventListener() {}
			close() {}
		}
	);
	arrival.search = '';
	sync.dispose();
	lookupsStore.reset();
	lookupsStore.loaded = true;
	lookupsStore.setAccounts(accounts);
	api.readSyncPlan.mockResolvedValue(plan);
});

describe('the sync page: the plan', () => {
	it('shows a block per login, a date field only where the start is editable, and leaves a busy login out', async () => {
		render(Page);

		const giro = await screen.findByRole('region', { name: 'Giro login' });
		expect(
			within(giro).getByText(/continues from the last sync, with an overlap/)
		).toBeInTheDocument();
		expect(within(giro).getAllByRole('button', { name: /^Start of/ })).toHaveLength(1);
		expect(within(giro).getByRole('button', { name: 'Start of Pocket' })).toBeInTheDocument();
		expect(within(giro).getByText('Documents')).toBeInTheDocument();
		// an account row of the plan is read by its account: its tile
		expect(
			giro.querySelector('[data-slot="plan-account"] span[style*="--tile-fg"]')
		).not.toBeNull();
		const busy = screen.getByRole('region', { name: 'Card login' });
		expect(within(busy).getByText('another sync is using this login')).toBeInTheDocument();
	});

	it('starts the sync with every login the plan shows, except the busy one', async () => {
		api.startSync.mockResolvedValue({ task_id: 't9', busy: [] });
		render(Page);
		await screen.findByRole('region', { name: 'Giro login' });

		await fireEvent.click(screen.getByRole('button', { name: 'Start sync' }));

		await waitFor(() =>
			expect(api.startSync).toHaveBeenCalledWith([
				{ instance_id: 1, account_id: 7 },
				{ instance_id: 1, account_id: 8 },
				{ instance_id: 1, kind: 'documents' }
			])
		);
	});

	it('shows a refused start above the button', async () => {
		api.startSync.mockRejectedValue(
			new ApiError(422, 'nothing_to_sync', 'There is nothing to sync.')
		);
		render(Page);
		await screen.findByRole('region', { name: 'Giro login' });

		await fireEvent.click(screen.getByRole('button', { name: 'Start sync' }));

		expect(await screen.findByText('There is nothing to sync.')).toBeInTheDocument();
		expect(sync.status).toBe('idle');
	});

	it('says there is nothing to fetch, with a link to the importers', async () => {
		api.readSyncPlan.mockResolvedValue([]);
		render(Page);

		expect(await screen.findByText('Nothing to fetch yet')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Open Importers' })).toHaveAttribute(
			'href',
			'/settings/importers'
		);
		expect(screen.queryByRole('button', { name: 'Start sync' })).toBeNull();
	});

	it('has no action in its header', async () => {
		render(Page);
		await screen.findByRole('region', { name: 'Giro login' });

		const header = document.querySelector('[data-slot="page-header"]')!;
		expect(within(header as HTMLElement).queryAllByRole('button')).toHaveLength(0);
	});
});

describe('the sync page: a running task and its prompt', () => {
	it('asks for the PIN when the page is opened after the prompt arrived', async () => {
		// the prompt event came while the user was on another page: it is only in the store
		hold(foldAll([ev(3, 'prompt', promptEvent(1, null))], replayed()));
		expect(sync.view.prompt).not.toBeNull();

		render(Page);

		expect(await screen.findByText('PIN for Giro login')).toBeInTheDocument();
		expect(screen.getByText('Signing in.')).toBeInTheDocument();
		expect(screen.getByLabelText('PIN')).toHaveAttribute('type', 'password');
		const dialog = screen.getByRole('dialog');
		expect(within(dialog).getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
		expect(within(dialog).getByRole('button', { name: 'Stop sync…' })).toBeInTheDocument();
		expect(within(dialog).getByText(/Expires at/)).toBeInTheDocument();
		expect(within(dialog).getByText(/Cancelling stops this login/)).toBeInTheDocument();
	});

	it('shows no dialog while no prompt is open, and offers "Stop sync…" on the page', async () => {
		hold(replayed());
		render(Page);

		await screen.findByRole('region', { name: 'Giro login' });
		expect(screen.queryByRole('dialog')).toBeNull();
		expect(screen.getByRole('button', { name: 'Stop sync…' })).toBeInTheDocument();
	});

	it('shows the dialog when a prompt arrives while the page is shown, and drops it when resolved', async () => {
		hold(replayed());
		render(Page);
		await screen.findByRole('region', { name: 'Giro login' });

		sync.view = foldAll([ev(3, 'prompt', promptEvent(1, null))], sync.view);
		expect(await screen.findByText('PIN for Giro login')).toBeInTheDocument();

		sync.view = foldAll(
			[ev(4, 'prompt_resolved', { prompt_id: 'p1', outcome: 'answered' })],
			sync.view
		);
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
	});

	it('never shows the dialog for a discovery, which another page hosts', async () => {
		hold(foldAll([ev(3, 'prompt', promptEvent(1, null))], replayed()));
		sync.kind = 'discovery';
		render(Page);

		await screen.findByText('Refreshing the accounts of a login.');
		expect(screen.queryByRole('dialog')).toBeNull();
	});

	it('sends the PIN with the prompt id', async () => {
		api.answerPrompt.mockResolvedValue(undefined);
		hold(foldAll([ev(3, 'prompt', promptEvent(1, null))], replayed()));
		render(Page);
		const field = await screen.findByLabelText('PIN');

		await fireEvent.input(field, { target: { value: '1234' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

		await waitFor(() =>
			expect(api.answerPrompt).toHaveBeenCalledWith('t1', { prompt_id: 'p1', value: '1234' })
		);
	});

	it('asks before stopping, with Cancel focused, and stops on the verb', async () => {
		api.abortTask.mockResolvedValue({});
		hold(replayed());
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Stop sync…' }));

		const dialog = await screen.findByRole('dialog', { name: 'Stop the sync?' });
		await waitFor(() =>
			expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
		);
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Stop sync' }));

		await waitFor(() => expect(api.abortTask).toHaveBeenCalledWith('t1'));
	});

	it('says "Stopping…" until the task ends', async () => {
		hold(replayed());
		sync.stopping = true;
		render(Page);

		expect(await screen.findByText('Stopping…')).toBeInTheDocument();
	});
});

describe('the sync page: progress and the report', () => {
	it('shows a card per login with a row per item, and a done row opens its summary', async () => {
		hold(
			foldAll(
				[
					ev(3, 'run_started', runStarted(1, 10, 7, '2026-10-08')),
					ev(4, 'run_finished', runFinished(1, 10, 7, { inserted: 12, skipped_by_identity: 31 })),
					ev(5, 'run_started', runStarted(1, 11, 8, '2026-01-01'))
				],
				replayed()
			)
		);
		render(Page);

		const card = await screen.findByRole('region', { name: 'Giro login' });
		expect(within(card).getByText('Done · 12 inserted · 31 skipped')).toBeInTheDocument();
		expect(within(card).getByText(/Fetching from Jan 1, 2026/)).toBeInTheDocument();
		const row = card.querySelector('[data-slot="item-row"]')!;
		expect(row.querySelector('span[style*="--tile-fg"] svg.lucide-landmark')).not.toBeNull();
		expect(row.querySelector('[data-slot="account-dot"]')).toBeNull();
		await fireEvent.click(within(card).getByRole('button', { name: /Giro, Done/ }));
		expect(within(card).getByText('12 rows')).toBeInTheDocument();
	});

	it('shows how a sync ended and goes back to the plan', async () => {
		hold(
			foldAll(
				[
					ev(3, 'run_started', runStarted(1, 10, 7)),
					ev(4, 'run_finished', runFinished(1, 10, 7)),
					ev(5, 'run_started', runStarted(1, 11, 8)),
					ev(6, 'run_finished', runFinished(1, 11, 8)),
					ev(7, 'task_ended', taskEnded({ ok: 2 }))
				],
				replayed()
			),
			'ended'
		);
		render(Page);

		expect(await screen.findByText('Finished: 2 runs ok')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Back to the plan' }));

		expect(sync.status).toBe('idle');
		expect(await screen.findByRole('button', { name: 'Start sync' })).toBeInTheDocument();
	});

	it('offers "Run again" for a login that failed and can be tried again, covering what did not finish', async () => {
		api.startSync.mockResolvedValue({ task_id: 't2', busy: [] });
		hold(
			foldAll(
				[
					ev(3, 'run_started', runStarted(1, 10, 7)),
					ev(4, 'run_finished', runFinished(1, 10, 7)),
					ev(5, 'instance_failed', instanceFailed(1)),
					ev(6, 'task_ended', taskEnded({ ok: 1, failed: 1 }))
				],
				replayed()
			),
			'ended'
		);
		render(Page);

		expect(
			await screen.findByText('SourceUnavailable: the bank did not answer')
		).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Run again' }));

		await waitFor(() =>
			expect(api.startSync).toHaveBeenCalledWith([{ instance_id: 1, account_id: 8 }])
		);
	});

	it('says what to fix, with a link to the login, where trying again will not help', async () => {
		hold(
			foldAll(
				[
					ev(
						3,
						'instance_failed',
						instanceFailed(1, { code: 'bank_setup_required', retryable: false })
					),
					ev(4, 'task_ended', taskEnded({ failed: 2 }))
				],
				replayed()
			),
			'ended'
		);
		render(Page);

		expect(
			await screen.findByText(/Trying again will not help yet\. Fix what the error says/)
		).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /settings/ })).toHaveAttribute(
			'href',
			'/settings/importers/1'
		);
		expect(screen.queryByRole('button', { name: 'Run again' })).toBeNull();
	});

	it('says an interrupted sync was, and offers the plan again', async () => {
		sync.kind = 'sync';
		sync.status = 'interrupted';
		render(Page);

		expect(await screen.findByText('This sync was interrupted')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Back to the plan' }));
		expect(sync.status).toBe('idle');
	});

	describe('arriving at a narrowed plan', () => {
		const endedView = () =>
			foldAll(
				[
					ev(3, 'run_started', runStarted(1, 10, 7)),
					ev(4, 'run_finished', runFinished(1, 10, 7)),
					ev(5, 'task_ended', taskEnded({ ok: 1 }))
				],
				replayed()
			);

		it('discards an ended sync and shows the narrowed plan, not its report', async () => {
			arrival.search = '?instance=1&account=8';
			hold(endedView(), 'ended');
			render(Page);

			expect(await screen.findByRole('button', { name: 'Start sync' })).toBeInTheDocument();
			expect(sync.status).toBe('idle');
			expect(screen.queryByText('Finished: 1 run ok')).toBeNull();
		});

		it('discards an interrupted sync the same way', async () => {
			arrival.search = '?instance=1';
			sync.kind = 'sync';
			sync.status = 'interrupted';
			render(Page);

			expect(await screen.findByRole('button', { name: 'Start sync' })).toBeInTheDocument();
			expect(screen.queryByText('This sync was interrupted')).toBeNull();
		});

		it('keeps showing the ended report when /sync is opened without a narrowing', async () => {
			hold(endedView(), 'ended');
			render(Page);

			expect(await screen.findByText('Finished: 1 run ok')).toBeInTheDocument();
			expect(sync.status).toBe('ended');
		});

		it('keeps the report of a narrowed sync that ends while the page stays open', async () => {
			arrival.search = '?instance=1&account=8';
			hold(replayed());
			render(Page);
			await screen.findByRole('region', { name: 'Giro login' });

			sync.view = endedView();
			sync.status = 'ended';

			expect(await screen.findByText('Finished: 1 run ok')).toBeInTheDocument();
			expect(sync.status).toBe('ended');
		});
	});
});
