// Sync (architecture §4.1–§4.3): the plan, the start, the active task and its status, the answer to
// a prompt, the abort, a discovery's start, and the event stream of a task. The shapes are the
// generated ones (`SyncEventPayloads` names the nine events); this module is also the only one that
// opens an `EventSource` (architecture §6.2: only `lib/api` knows that URLs exist).
import { request } from './http.js';

type Schemas = import('../types/api.js').components['schemas'];

/** One login of the plan: its accounts with their starts, its documents, and whether it is held. */
export type PlanInstance = Schemas['PlanInstanceOut'];
export type PlanAccount = Schemas['PlanAccountOut'];
export type SyncItem = Schemas['SyncItem'];
export type TaskStatus = Schemas['TaskStatusOut'];
export type TaskKind = TaskStatus['kind'];
export type DiscoveryResult = Schemas['DiscoveryResultOut'];
export type DiscoveryEntry = Schemas['DiscoveryEntryOut'];

export type SyncEventPayloads = Schemas['SyncEventPayloads'];
export type SyncEventName = keyof SyncEventPayloads;
/** An event as the stream delivers it: its id, its name and the payload of that name. */
export type SyncEvent = {
	[N in SyncEventName]: { id: number; name: N; data: SyncEventPayloads[N] };
}[SyncEventName];

/** What a prompt asks (architecture §5.5): one of four kinds. */
export type PromptBody = NonNullable<SyncEventPayloads['prompt']['prompt']>;
export type PromptOutcome = SyncEventPayloads['prompt_resolved']['outcome'];

/** An answer to the open prompt, or its cancel; the value is a secret and is never kept. */
export type PromptAnswer =
	{ prompt_id: string; value: string } | { prompt_id: string; cancel: true };

/** What "sync everything" would do (a bare list of the logins the user may run). */
export function readSyncPlan(signal?: AbortSignal): Promise<PlanInstance[]> {
	return request<PlanInstance[]>('GET', '/api/sync/plan', { signal });
}

/** Start a sync of these items; refused as a whole (`task_active`, `instance_busy`, `nothing_to_sync`…). */
export function startSync(
	items: readonly SyncItem[]
): Promise<{ task_id: string; busy: number[] }> {
	return request('POST', '/api/sync', { body: { items } });
}

/** A task's status; an unknown (or evicted) task is a 404 `not_found`. */
export function getTaskStatus(taskId: string, signal?: AbortSignal): Promise<TaskStatus> {
	return request<TaskStatus>('GET', `/api/sync/tasks/${encodeURIComponent(taskId)}`, { signal });
}

/** Answer the open prompt or cancel it. A 409 `conflict` with `prompt_not_open` is an answer too late. */
export function answerPrompt(taskId: string, answer: PromptAnswer): Promise<void> {
	return request<void>('POST', `/api/sync/tasks/${encodeURIComponent(taskId)}/input`, {
		body: answer
	});
}

/** Stop the task: 202 while it runs, 200 for one that has ended. */
export function abortTask(taskId: string): Promise<TaskStatus> {
	return request<TaskStatus>('POST', `/api/sync/tasks/${encodeURIComponent(taskId)}/abort`);
}

/** Start the discovery of an instance's accounts; it is a task like a sync (its result is on its status). */
export function discoverAccounts(instanceId: number): Promise<{ task_id: string }> {
	return request('POST', `/api/importers/instances/${instanceId}/discover-accounts`);
}

// ---- the event stream -------------------------------------------------------------------------

export const SYNC_EVENT_NAMES = [
	'task_started',
	'instance_started',
	'run_started',
	'prompt',
	'prompt_resolved',
	'run_finished',
	'run_failed',
	'instance_failed',
	'task_ended'
] as const satisfies readonly SyncEventName[];

/** The part of an `EventSource` this client uses (a test passes a fake). */
export type EventSourceLike = {
	readonly readyState: number;
	addEventListener(name: string, listener: (event: MessageEvent) => void): void;
	onerror: ((event: Event) => void) | null;
	close(): void;
};

export type EventSourceFactory = (url: string) => EventSourceLike;

export type TaskEventsHandlers = {
	/** one parsed event; ids rise by one from 1, a replay starts at 1 again */
	onEvent: (event: SyncEvent) => void;
	/** the source is closed for good without a `task_ended` (an HTTP error answered): ask the status */
	onClosed: () => void;
};

export type TaskEvents = { close: () => void };

const CLOSED = 2; // EventSource.CLOSED

/**
 * Attach to a task's stream (same origin, so the session cookie goes along): one listener per event
 * name, the JSON of each parsed. A task that ended closes it (the server closes too, and an
 * `EventSource` would reconnect). While the browser reconnects by itself nothing is reported; a
 * source that reaches CLOSED without a `task_ended` is `onClosed`.
 */
export function openTaskEvents(
	taskId: string,
	handlers: TaskEventsHandlers,
	factory: EventSourceFactory = (url) => new EventSource(url)
): TaskEvents {
	const source = factory(`/api/sync/tasks/${encodeURIComponent(taskId)}/events`);
	let done = false;
	const close = () => {
		done = true;
		source.close();
	};
	for (const name of SYNC_EVENT_NAMES) {
		source.addEventListener(name, (message) => {
			if (done) return;
			let data: unknown;
			try {
				data = JSON.parse(message.data as string);
			} catch {
				return;
			}
			const event = { id: Number(message.lastEventId), name, data } as SyncEvent;
			if (name === 'task_ended') close();
			handlers.onEvent(event);
		});
	}
	source.onerror = () => {
		if (done || source.readyState !== CLOSED) return;
		done = true;
		handlers.onClosed();
	};
	return { close };
}
