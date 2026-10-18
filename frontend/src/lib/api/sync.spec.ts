import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './http.js';
import {
	abortTask,
	answerPrompt,
	discoverAccounts,
	getActiveTask,
	getTaskStatus,
	openTaskEvents,
	readSyncPlan,
	SYNC_EVENT_NAMES,
	startSync,
	type EventSourceLike,
	type SyncEvent
} from './sync.js';

const fetchMock = vi.fn();

function reply(payload: unknown, status = 200): Response {
	return new Response(JSON.stringify(payload), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

function last(): [string, RequestInit] {
	return fetchMock.mock.calls.at(-1) as [string, RequestInit];
}

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('the sync operations', () => {
	it('reads the plan as a bare list', async () => {
		fetchMock.mockImplementation(async () => reply([{ instance_id: 1 }]));
		expect(await readSyncPlan()).toEqual([{ instance_id: 1 }]);
		expect(last()[0]).toBe('/api/sync/plan');
	});

	it('starts a sync with explicit items', async () => {
		fetchMock.mockImplementation(async () => reply({ task_id: 'abc', busy: [] }, 202));
		const items = [{ instance_id: 1, account_id: 7, since: '2026-01-01' }];
		expect(await startSync(items)).toEqual({ task_id: 'abc', busy: [] });
		const [path, init] = last();
		expect(path).toBe('/api/sync');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual({ items });
	});

	it('maps the refusals of a start to their codes', async () => {
		fetchMock.mockImplementation(async () =>
			reply({ error: { code: 'task_active', message: 'x', details: { task_id: 't1' } } }, 409)
		);
		await expect(startSync([{ instance_id: 1 }])).rejects.toMatchObject({
			status: 409,
			code: 'task_active'
		});
		fetchMock.mockImplementation(async () =>
			reply({ error: { code: 'nothing_to_sync', message: 'x', details: null } }, 422)
		);
		await expect(startSync([])).rejects.toBeInstanceOf(ApiError);
	});

	it('answers 204 for no active task with null, and a status otherwise', async () => {
		fetchMock.mockImplementation(async () => new Response(null, { status: 204 }));
		expect(await getActiveTask()).toBeNull();
		expect(last()[0]).toBe('/api/sync/active');

		fetchMock.mockImplementation(async () => reply({ task_id: 't', status: 'running' }));
		expect(await getActiveTask()).toMatchObject({ task_id: 't' });
	});

	it('reads a status and aborts a task by its id', async () => {
		fetchMock.mockImplementation(async () => reply({ task_id: 't/1' }));
		await getTaskStatus('t/1');
		expect(last()[0]).toBe('/api/sync/tasks/t%2F1');
		await abortTask('t1');
		expect(last()[0]).toBe('/api/sync/tasks/t1/abort');
		expect(last()[1].method).toBe('POST');
	});

	it('answers or cancels a prompt with its id', async () => {
		fetchMock.mockImplementation(async () => new Response(null, { status: 204 }));
		await answerPrompt('t1', { prompt_id: 'p1', value: '1234' });
		expect(JSON.parse(last()[1].body as string)).toEqual({ prompt_id: 'p1', value: '1234' });
		expect(last()[0]).toBe('/api/sync/tasks/t1/input');
		await answerPrompt('t1', { prompt_id: 'p1', cancel: true });
		expect(JSON.parse(last()[1].body as string)).toEqual({ prompt_id: 'p1', cancel: true });
	});

	it('starts a discovery', async () => {
		fetchMock.mockImplementation(async () => reply({ task_id: 'd1' }, 202));
		expect(await discoverAccounts(3)).toEqual({ task_id: 'd1' });
		expect(last()[0]).toBe('/api/importers/instances/3/discover-accounts');
		expect(last()[1].method).toBe('POST');
	});
});

class FakeSource implements EventSourceLike {
	readyState = 1;
	onerror: ((event: Event) => void) | null = null;
	closed = false;
	listeners = new Map<string, (event: MessageEvent) => void>();
	constructor(readonly url: string) {}
	addEventListener(name: string, listener: (event: MessageEvent) => void) {
		this.listeners.set(name, listener);
	}
	close() {
		this.closed = true;
		this.readyState = 2;
	}
	emit(name: string, id: number, data: unknown) {
		this.listeners.get(name)?.({ data: JSON.stringify(data), lastEventId: String(id) } as MessageEvent);
	}
}

function open() {
	const sources: FakeSource[] = [];
	const events: SyncEvent[] = [];
	const onClosed = vi.fn();
	const handle = openTaskEvents('t1', { onEvent: (e) => events.push(e), onClosed }, (url) => {
		const source = new FakeSource(url);
		sources.push(source);
		return source;
	});
	return { source: sources[0], events, onClosed, handle };
}

describe('openTaskEvents', () => {
	it('listens once per event name on the task stream', () => {
		const { source } = open();
		expect(source.url).toBe('/api/sync/tasks/t1/events');
		expect([...source.listeners.keys()].sort()).toEqual([...SYNC_EVENT_NAMES].sort());
	});

	it('passes each event with its id, name and parsed data', () => {
		const { source, events } = open();
		source.emit('instance_started', 2, { instance_id: 4 });
		expect(events).toEqual([{ id: 2, name: 'instance_started', data: { instance_id: 4 } }]);
	});

	it('ignores a frame that is not JSON', () => {
		const { source, events } = open();
		source.listeners.get('prompt')?.({ data: '{nope', lastEventId: '1' } as MessageEvent);
		expect(events).toEqual([]);
	});

	it('closes on task_ended, after passing it on', () => {
		const { source, events } = open();
		source.emit('task_ended', 9, { outcome: 'completed', ok: 1, failed: 0, not_started: [] });
		expect(source.closed).toBe(true);
		expect(events.map((e) => e.name)).toEqual(['task_ended']);
		source.emit('instance_started', 10, { instance_id: 1 });
		expect(events).toHaveLength(1);
	});

	it('reports a source that closed for good, and stays silent while it reconnects', () => {
		const { source, onClosed } = open();
		source.readyState = 0; // CONNECTING: the browser retries by itself
		source.onerror?.(new Event('error'));
		expect(onClosed).not.toHaveBeenCalled();
		source.readyState = 2;
		source.onerror?.(new Event('error'));
		expect(onClosed).toHaveBeenCalledTimes(1);
	});

	it('does not report a close it asked for itself', () => {
		const { source, onClosed, handle } = open();
		handle.close();
		source.onerror?.(new Event('error'));
		expect(onClosed).not.toHaveBeenCalled();
	});
});
