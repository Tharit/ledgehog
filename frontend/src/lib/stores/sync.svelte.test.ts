import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/http.js';
import {
	abortTask,
	answerPrompt,
	discoverAccounts,
	getTaskStatus,
	startSync,
	type SyncEvent,
	type TaskEventsHandlers,
	type TaskStatus
} from '#lib/api/sync.js';
import {
	ev,
	instanceFailed,
	promptEvent,
	runStarted,
	taskEnded,
	taskStarted
} from '#lib/sync/fixtures.js';
import { SyncStore } from './sync.svelte.js';

vi.mock('#lib/api/sync.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/sync.js')>()),
	startSync: vi.fn(),
	getTaskStatus: vi.fn(),
	answerPrompt: vi.fn(),
	abortTask: vi.fn(),
	discoverAccounts: vi.fn()
}));

class FakeStream {
	closed = false;
	constructor(
		readonly taskId: string,
		readonly handlers: TaskEventsHandlers
	) {}
	push(...events: SyncEvent[]) {
		for (const event of events) this.handlers.onEvent(event);
	}
	close() {
		this.closed = true;
	}
	/** the source reached CLOSED without a task_ended */
	giveUp() {
		this.handlers.onClosed();
	}
}

let streams: FakeStream[];

function store() {
	return new SyncStore((taskId, handlers) => {
		const stream = new FakeStream(taskId, handlers);
		streams.push(stream);
		return stream;
	});
}

const running = (over: Partial<TaskStatus> = {}): TaskStatus => ({
	task_id: 't1',
	kind: 'sync',
	status: 'running',
	aborting: false,
	outcome: null,
	last_event_id: 3,
	result: null,
	...over
});

const begin = ev(1, 'task_started', taskStarted([{ id: 1, accounts: [7] }]));
const signing = ev(2, 'instance_started', { instance_id: 1 });
const asking = ev(3, 'prompt', promptEvent(1, null));
const resolved = ev(4, 'prompt_resolved', { prompt_id: 'p1', outcome: 'answered' });

async function attached() {
	vi.mocked(getTaskStatus).mockResolvedValue(running());
	const s = store();
	await s.follow('t1');
	streams[0].push(begin, signing, asking);
	return s;
}

beforeEach(() => {
	vi.resetAllMocks();
	streams = [];
});

describe('SyncStore: attaching', () => {
	it('stays idle when the server has no active task', async () => {
		const s = store();
		await s.follow(null);
		expect(s.status).toBe('idle');
		expect(streams).toHaveLength(0);
		expect(getTaskStatus).not.toHaveBeenCalled();
	});

	it('attaches to the active task and rebuilds its view, an open prompt included, from the replay', async () => {
		const s = await attached();
		expect(streams[0].taskId).toBe('t1');
		expect(s.status).toBe('running');
		expect(s.kind).toBe('sync');
		expect(s.view.instances).toHaveLength(1);
		expect(s.view.prompt).toMatchObject({ promptId: 'p1', body: { kind: 'secret' } });
	});

	it('attaches when the active task appears in a later read, as a sync started in another tab', async () => {
		vi.mocked(getTaskStatus).mockResolvedValue(running({ task_id: 't9' }));
		const s = store();
		await s.follow(null);
		expect(s.status).toBe('idle');

		await s.follow('t9');
		expect(streams).toHaveLength(1);
		expect(streams[0].taskId).toBe('t9');
		expect(s.status).toBe('attaching');
		expect(s.taskId).toBe('t9');
	});

	it('does not attach again to the task it is attached to, nor twice while the status is being read', async () => {
		const s = await attached();
		await s.follow('t1');
		expect(streams).toHaveLength(1);

		let release!: (status: TaskStatus) => void;
		vi.mocked(getTaskStatus).mockImplementation(
			() => new Promise((resolve) => (release = resolve))
		);
		const other = store();
		const first = other.follow('t2');
		const second = other.follow('t2');
		release(running({ task_id: 't2' }));
		await Promise.all([first, second]);
		expect(streams).toHaveLength(2);
	});

	it('picks up the abort already under way from the status it attaches by', async () => {
		vi.mocked(getTaskStatus).mockResolvedValue(running({ aborting: true }));
		const s = store();
		await s.follow('t1');
		expect(s.stopping).toBe(true);
	});

	it('reads the status again when the server has no active task and the end was not seen', async () => {
		const s = await attached();
		vi.mocked(getTaskStatus).mockRejectedValue(new ApiError(404, 'not_found', 'gone'));
		await s.follow(null);
		expect(s.status).toBe('interrupted');
	});

	it('leaves an ended task alone when the server has no active task', async () => {
		const s = await attached();
		streams[0].push(resolved, ev(5, 'task_ended', taskEnded()));
		vi.mocked(getTaskStatus).mockClear();
		await s.follow(null);
		expect(getTaskStatus).not.toHaveBeenCalled();
		expect(s.status).toBe('ended');
	});

	it('closes the prompt when the stream resolves it, as the other tab answered', async () => {
		const s = await attached();
		streams[0].push(resolved);
		expect(s.view.prompt).toBeNull();
		expect(s.status).toBe('running');
	});

	it('ends on task_ended and closes the source', async () => {
		const s = await attached();
		streams[0].push(
			resolved,
			ev(5, 'instance_failed', instanceFailed(1)),
			ev(6, 'task_ended', taskEnded({ failed: 1 }))
		);
		expect(s.status).toBe('ended');
		expect(streams[0].closed).toBe(true);
		expect(s.view.end?.failed).toBe(1);
	});

	it('is interrupted when the stream is lost and the server no longer knows the task', async () => {
		const s = await attached();
		vi.mocked(getTaskStatus).mockRejectedValue(new ApiError(404, 'not_found', 'no such task'));
		streams[0].giveUp();
		await vi.waitFor(() => expect(s.status).toBe('interrupted'));
		expect(streams[0].closed).toBe(true);
	});

	it('attaches again with a fresh view when the stream is lost and the task is known', async () => {
		const s = await attached();
		vi.mocked(getTaskStatus).mockResolvedValue(running({ aborting: true }));
		streams[0].giveUp();
		await vi.waitFor(() => expect(streams).toHaveLength(2));
		expect(s.view.instances).toHaveLength(0);
		expect(s.stopping).toBe(true);
		streams[1].push(begin, signing, asking);
		expect(s.view.prompt?.promptId).toBe('p1');
		expect(s.status).toBe('running');
	});

	it('gives up a stream that keeps closing', async () => {
		const s = await attached();
		vi.mocked(getTaskStatus).mockResolvedValue(running());
		for (let round = 0; round < 4; round++) {
			const before = streams.length;
			streams.at(-1)!.giveUp();
			if (round < 3) await vi.waitFor(() => expect(streams).toHaveLength(before + 1));
		}
		await vi.waitFor(() => expect(s.status).toBe('interrupted'));
	});
});

describe('SyncStore: starting', () => {
	it('starts a sync and attaches to its task', async () => {
		vi.mocked(startSync).mockResolvedValue({ task_id: 't9', busy: [] });
		const s = store();
		const items = [{ instance_id: 1, account_id: 7 }];
		expect(await s.start(items)).toBeNull();
		expect(startSync).toHaveBeenCalledWith(items);
		expect(s.taskId).toBe('t9');
		expect(s.status).toBe('attaching');
		expect(s.homePath).toBe('/sync');
		streams[0].push(begin);
		expect(s.status).toBe('running');
	});

	it('reports a refused start and stays idle', async () => {
		vi.mocked(startSync).mockRejectedValue(
			new ApiError(409, 'task_active', 'a sync is running', { task_id: 'other' })
		);
		const s = store();
		expect(await s.start([{ instance_id: 1 }])).toEqual({
			code: 'task_active',
			message: 'a sync is running'
		});
		expect(s.status).toBe('idle');
		expect(streams).toHaveLength(0);
	});

	it('hosts a discovery on its instance page', async () => {
		vi.mocked(discoverAccounts).mockResolvedValue({ task_id: 'd1' });
		const s = store();
		expect(await s.startDiscovery(3)).toBeNull();
		expect(s.kind).toBe('discovery');
		expect(s.homePath).toBe('/settings/importers/3/accounts');
	});

	it('replaces an ended task by a new one', async () => {
		const s = await attached();
		streams[0].push(resolved, ev(5, 'task_ended', taskEnded()));
		vi.mocked(startSync).mockResolvedValue({ task_id: 't2', busy: [] });
		await s.start([{ instance_id: 1 }]);
		expect(s.taskId).toBe('t2');
		expect(s.view.end).toBeNull();
		expect(streams).toHaveLength(2);
	});

	it('goes back to the plan only from an ended task', async () => {
		const s = await attached();
		s.reset();
		expect(s.status).toBe('running');
		streams[0].push(resolved, ev(5, 'task_ended', taskEnded()));
		s.reset();
		expect(s.status).toBe('idle');
		expect(s.taskId).toBeNull();
	});

	it('marks an ended task seen, and not a running one', async () => {
		const s = await attached();
		s.markSeen();
		expect(s.seen).toBe(false);
		streams[0].push(resolved, ev(5, 'task_ended', taskEnded()));
		s.markSeen();
		expect(s.seen).toBe(true);
	});
});

describe('SyncStore: answering', () => {
	it('sends the value with the prompt id, and waits for the stream to close the prompt', async () => {
		vi.mocked(answerPrompt).mockResolvedValue(undefined);
		const s = await attached();
		await s.answer('1234');
		expect(answerPrompt).toHaveBeenCalledWith('t1', { prompt_id: 'p1', value: '1234' });
		expect(s.view.prompt).not.toBeNull();
		expect(s.sending).toBe(true);
		streams[0].push(resolved);
		expect(s.sending).toBe(false);
		expect(s.view.prompt).toBeNull();
	});

	it('sends a cancel', async () => {
		vi.mocked(answerPrompt).mockResolvedValue(undefined);
		const s = await attached();
		await s.cancelPrompt();
		expect(answerPrompt).toHaveBeenCalledWith('t1', { prompt_id: 'p1', cancel: true });
	});

	it('dismisses a 409 prompt_not_open silently', async () => {
		vi.mocked(answerPrompt).mockRejectedValue(
			new ApiError(409, 'conflict', 'not open', { reason: 'prompt_not_open' })
		);
		const s = await attached();
		await s.answer('1234');
		expect(s.sending).toBe(false);
		expect(s.fieldError).toBeNull();
		expect(s.sendError).toBeNull();
	});

	it('keeps the prompt open under a 422 and shows the refusal under the field', async () => {
		vi.mocked(answerPrompt).mockRejectedValue(
			new ApiError(422, 'validation_error', 'invalid', [
				{ location: ['body', 'value'], message: 'The PIN is empty.', type: 'value_error' }
			])
		);
		const s = await attached();
		await s.answer('');
		expect(s.fieldError).toBe('The PIN is empty.');
		expect(s.sending).toBe(false);
		expect(s.view.prompt).not.toBeNull();
	});

	it('shows a failure to send in the feedback slot, the dialog kept', async () => {
		vi.mocked(answerPrompt).mockRejectedValue(
			new ApiError(0, 'network_error', 'The server could not be reached.')
		);
		const s = await attached();
		await s.answer('1234');
		expect(s.sendError).toBe('The server could not be reached.');
		expect(s.view.prompt).not.toBeNull();
	});

	it('clears an earlier refusal when the next prompt opens', async () => {
		vi.mocked(answerPrompt).mockRejectedValue(new ApiError(422, 'validation_error', 'bad'));
		const s = await attached();
		await s.answer('x');
		expect(s.fieldError).toBe('bad');
		streams[0].push(resolved, ev(5, 'prompt', promptEvent(1, null, undefined, 'p2')));
		expect(s.fieldError).toBeNull();
		expect(s.view.prompt?.promptId).toBe('p2');
	});
});

describe('SyncStore: stopping', () => {
	it('says stopping until the task ends', async () => {
		vi.mocked(abortTask).mockResolvedValue(running({ aborting: true }));
		const s = await attached();
		expect(await s.abort()).toBeNull();
		expect(abortTask).toHaveBeenCalledWith('t1');
		expect(s.stopping).toBe(true);
		streams[0].push(resolved, ev(5, 'task_ended', taskEnded({ outcome: 'aborted' })));
		expect(s.stopping).toBe(false);
		expect(s.status).toBe('ended');
	});

	it('returns the failure of an abort that did not go through', async () => {
		vi.mocked(abortTask).mockRejectedValue(
			new ApiError(0, 'network_error', 'The server could not be reached.')
		);
		const s = await attached();
		expect(await s.abort()).toBe('The server could not be reached.');
		expect(s.stopping).toBe(false);
	});

	it('follows a task whose run began, for the item rows', async () => {
		const s = await attached();
		streams[0].push(resolved, ev(5, 'run_started', runStarted(1, 10, 7)));
		expect(s.view.instances[0].items[0].state).toBe('fetching');
	});
});
