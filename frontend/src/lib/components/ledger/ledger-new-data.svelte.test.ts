import { render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { signedIn } from '#lib/entry-form/fixtures.js';
import { account } from '#lib/ledger/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { sync } from '#lib/stores/sync.svelte.js';
import {
	promptEvent,
	runFinished,
	runStarted,
	taskEnded,
	taskStarted
} from '#lib/sync/fixtures.js';
import Page from '../../../routes/ledger/+page.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	listEntries: vi.fn(),
	listAccounts: vi.fn(),
	listCategories: vi.fn(),
	listPayees: vi.fn(),
	listTags: vi.fn(),
	getActiveTask: vi.fn()
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

/** the browser's EventSource of the task stream: the test pushes the frames the server would send */
type Frame = { id: number; name: string; data: unknown };
let source: { frames: (frame: Frame) => void } | null = null;
class FakeEventSource {
	readyState = 1;
	onerror = null;
	#listeners = new Map<string, (event: MessageEvent) => void>();
	constructor() {
		source = {
			frames: (f) =>
				this.#listeners.get(f.name)?.({
					data: JSON.stringify(f.data),
					lastEventId: String(f.id)
				} as MessageEvent)
		};
	}
	addEventListener(name: string, listener: (event: MessageEvent) => void) {
		this.#listeners.set(name, listener);
	}
	close() {}
}

const frame = (id: number, name: string, data: unknown): Frame => ({ id, name, data });

beforeEach(() => {
	vi.resetAllMocks();
	vi.stubGlobal('EventSource', FakeEventSource);
	sync.dispose();
	lookupsStore.reset();
	signedIn();
	api.listEntries.mockResolvedValue({ entries: [], total: 0 });
	api.listAccounts.mockResolvedValue([account({ id: 7 })]);
	api.listCategories.mockResolvedValue([]);
	api.listPayees.mockResolvedValue([]);
	api.listTags.mockResolvedValue([]);
});

describe('the ledger, a snapshot, while a sync it did not start runs', () => {
	it('shows the notice once a run wrote rows, keeps it through the end of the sync and the refetch of the non-snapshot lists, and never refetches itself', async () => {
		// tab B started the sync and left the PIN prompt open; this tab opens the ledger now
		api.getActiveTask.mockResolvedValue({
			task_id: 't1',
			kind: 'sync',
			status: 'running',
			aborting: false,
			outcome: null,
			last_event_id: 3,
			result: null
		});
		render(Page);
		await waitFor(() => expect(api.listEntries).toHaveBeenCalledTimes(1));
		await sync.mount();
		source!.frames(frame(1, 'task_started', taskStarted([{ id: 1, accounts: [7] }])));
		source!.frames(frame(2, 'instance_started', { instance_id: 1 }));
		source!.frames(frame(3, 'prompt', promptEvent(1, null)));
		expect(screen.queryByText(/New data from a sync/)).toBeNull();

		// tab B answers: the run inserts rows
		source!.frames(frame(4, 'prompt_resolved', { prompt_id: 'p1', outcome: 'answered' }));
		source!.frames(frame(5, 'run_started', runStarted(1, 10, 7)));
		source!.frames(frame(6, 'run_finished', runFinished(1, 10, 7, { inserted: 30 })));

		expect(await screen.findByText('New data from a sync —')).toBeInTheDocument();

		// the sync ends; the non-snapshot lists refetch and the shared lookups move
		source!.frames(frame(7, 'task_ended', taskEnded({ ok: 1 })));
		await lookupsStore.reload();
		lookupsStore.setAccounts([account({ id: 7, name: 'Renamed' })]);
		await new Promise((resolve) => setTimeout(resolve, 20));

		expect(screen.getByText('New data from a sync —')).toBeInTheDocument();
		expect(api.listEntries).toHaveBeenCalledTimes(1);
	});
});
