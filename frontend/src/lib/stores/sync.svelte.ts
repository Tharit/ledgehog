// The active task, a sync or a discovery (architecture §6.4): ONE store, mounted at the root layout
// once the session is known, so that the task outlives the page that started it. It asks the server
// for the user's active task (no token is kept anywhere), attaches to its event stream, and holds
// the folded view. A prompt is open if and only if `view.prompt` is set; the page that hosts the task
// reads it from here when it mounts, so a prompt that arrived elsewhere is shown on a later visit.
import {
	ApiError,
	abortTask,
	answerPrompt,
	discoverAccounts,
	getActiveTask,
	getTaskStatus,
	openTaskEvents,
	readSyncPlan,
	startSync,
	type PromptAnswer,
	type SyncEvent,
	type SyncItem,
	type TaskEvents,
	type TaskEventsHandlers,
	type TaskKind,
	type TaskStatus
} from '#lib/api/index.js';
import { discoveryUrl } from '#lib/importers/links.js';
import { initialView, foldEvent, type TaskView } from '#lib/sync/events.js';
import { refusalOf, type EntryDeps, type StartRefusal } from '#lib/sync/entry.js';
import { eventWroteRows } from '#lib/sync/new-data.js';
import type { TaskPhase } from '#lib/sync/status.js';

export type OpenEvents = (taskId: string, handlers: TaskEventsHandlers) => TaskEvents;

/** How often a stream that keeps closing for good is attached again before the task counts as lost. */
const REATTACHES = 3;

/** The address of a discovery's page (ux/views/importers.md "Refresh accounts"). */
export function discoveryPath(instanceId: number): string {
	return discoveryUrl(instanceId);
}

function validationText(error: ApiError): string {
	const first = Array.isArray(error.details) ? error.details[0] : null;
	return typeof first?.message === 'string' && first.message ? first.message : error.message;
}

function promptNotOpen(error: unknown): boolean {
	return (
		error instanceof ApiError &&
		error.status === 409 &&
		(error.details as { reason?: string } | null)?.reason === 'prompt_not_open'
	);
}

export class SyncStore {
	/** `attaching` until the first event arrives (the replay), `running` after, then `ended` or `interrupted` */
	status = $state<TaskPhase>('idle');
	taskId = $state<string | null>(null);
	kind = $state<TaskKind | null>(null);
	view = $state.raw<TaskView>(initialView());
	/** "Stopping…": an abort was accepted and the task has not ended yet */
	stopping = $state(false);
	/** the sync page was opened since the task ended: the indicator's "Finished" line goes */
	seen = $state(false);
	/** an answer is on its way, or was accepted and the prompt not yet resolved */
	sending = $state(false);
	/** the server's refusal of the answer, shown under the field; the prompt stays open */
	fieldError = $state<string | null>(null);
	/** a failure to send, shown in the dialog's feedback slot */
	sendError = $state<string | null>(null);

	/**
	 * Revisions, never counts (architecture §6.4): `dataRevision` moves when a run of this session
	 * wrote rows, `endRevision` when a sync (or discovery) ended. A view remembers the former it
	 * fetched at; a list that is not a snapshot refetches when the latter moves.
	 */
	dataRevision = $state(0);
	endRevision = $state(0);

	#discoveryInstance = $state<number | null>(null);
	/** the last event id already noted: a replay of the stream (a reattach) is not news again */
	#notedUpTo = 0;
	/** where the task is hosted: `/sync`, or a discovery's page */
	readonly homePath = $derived(
		this.kind === 'discovery'
			? discoveryPath(this.#discoveryInstance ?? this.view.instances[0]?.instanceId ?? 0)
			: '/sync'
	);

	#open: OpenEvents;
	#events: TaskEvents | null = null;
	#mounted = false;
	#reattaches = 0;

	constructor(open: OpenEvents = openTaskEvents) {
		this.#open = open;
	}

	/** The app is authenticated: ask for the active task and attach to it (a reload picks it up again). */
	async mount(): Promise<void> {
		if (this.#mounted) return;
		this.#mounted = true;
		let active: TaskStatus | null;
		try {
			active = await getActiveTask();
		} catch {
			return; // nothing to attach to; the next start says what is wrong
		}
		if (active && this.status === 'idle') {
			this.#begin(active.task_id, active.kind, null, active.aborting);
			// what the replay delivers happened before this page loaded: its views already hold it
			this.#notedUpTo = active.last_event_id;
		}
	}

	/** The session ended or the app is going: drop the task, keep nothing. */
	dispose(): void {
		this.#clear();
		this.#mounted = false;
	}

	/** Start a sync of these items. A refusal leaves the store as it was and is returned for the page that asked. */
	async start(items: readonly SyncItem[]): Promise<StartRefusal | null> {
		let started: { task_id: string };
		try {
			started = await startSync(items);
		} catch (error) {
			return refusalOf(error);
		}
		this.#begin(started.task_id, 'sync');
		return null;
	}

	/** Start the discovery of an instance's accounts; it is hosted by its own page. */
	async startDiscovery(instanceId: number): Promise<StartRefusal | null> {
		let started: { task_id: string };
		try {
			started = await discoverAccounts(instanceId);
		} catch (error) {
			return refusalOf(error);
		}
		this.#begin(started.task_id, 'discovery', instanceId);
		return null;
	}

	/** Answer the open prompt. It closes when the stream says it is resolved, not on the answer. */
	answer(value: string): Promise<void> {
		const prompt = this.view.prompt;
		return prompt ? this.#send({ prompt_id: prompt.promptId, value }) : Promise.resolve();
	}

	/** Cancel the open prompt: that login's sync ends, its runs fail and can be run again. */
	cancelPrompt(): Promise<void> {
		const prompt = this.view.prompt;
		return prompt ? this.#send({ prompt_id: prompt.promptId, cancel: true }) : Promise.resolve();
	}

	/** Stop the task. Returns the failure's text, or null once the server has accepted it. */
	async abort(): Promise<string | null> {
		const taskId = this.taskId;
		if (!taskId || this.status === 'ended') return null;
		this.stopping = true;
		try {
			await abortTask(taskId);
			return null;
		} catch (error) {
			this.stopping = false;
			return refusalOf(error).message;
		}
	}

	/** "Back to the plan": forget an ended (or interrupted) task. A running one is not dropped. */
	reset(): void {
		if (this.status === 'ended' || this.status === 'interrupted') this.#clear();
	}

	/** The sync page was opened: an ended task's line leaves the indicator. */
	markSeen(): void {
		if (this.status === 'ended') this.seen = true;
	}

	// ---- internals ----------------------------------------------------------------------------

	async #send(answer: PromptAnswer): Promise<void> {
		const taskId = this.taskId;
		if (!taskId) return;
		this.sending = true;
		this.fieldError = null;
		this.sendError = null;
		try {
			await answerPrompt(taskId, answer);
			// accepted: the dialog stays, sending, until `prompt_resolved` closes it (in every tab)
		} catch (error) {
			this.sending = false;
			if (promptNotOpen(error)) return; // someone else answered, or the task moved on: the stream says so
			if (error instanceof ApiError && error.status === 422) {
				this.fieldError = validationText(error);
			} else {
				this.sendError = refusalOf(error).message;
			}
		}
	}

	#begin(
		taskId: string,
		kind: TaskKind,
		discoveryInstance: number | null = null,
		aborting = false
	) {
		this.#clear();
		this.taskId = taskId;
		this.kind = kind;
		this.#notedUpTo = 0;
		this.#discoveryInstance = discoveryInstance;
		this.stopping = aborting;
		this.status = 'attaching';
		this.#attach(taskId);
	}

	#attach(taskId: string) {
		this.#events?.close();
		this.#events = this.#open(taskId, {
			onEvent: (event) => this.#apply(event),
			onClosed: () => void this.#recheck(taskId)
		});
	}

	#apply(event: SyncEvent) {
		this.#reattaches = 0;
		this.#note(event);
		const before = this.view.prompt?.promptId ?? null;
		this.view = foldEvent(this.view, event);
		if (this.view.kind) this.kind = this.view.kind;
		if (this.view.prompt?.promptId !== before) this.#resetPrompt();
		if (event.name === 'task_ended') {
			this.#events?.close();
			this.#events = null;
			this.stopping = false;
			this.status = 'ended';
		} else if (this.status === 'attaching') {
			this.status = 'running';
		}
	}

	/** Note what an event says to the views: rows written, a task ended; each event once. */
	#note(event: SyncEvent) {
		if (event.id <= this.#notedUpTo) return;
		this.#notedUpTo = event.id;
		if (eventWroteRows(event)) this.dataRevision++;
		if (event.name === 'task_ended') this.endRevision++;
	}

	/** The stream closed for good without a `task_ended`: a status means attach again, nothing means lost. */
	async #recheck(taskId: string) {
		if (taskId !== this.taskId) return;
		try {
			if (++this.#reattaches > REATTACHES) throw new Error('the stream does not stay');
			const status = await getTaskStatus(taskId);
			if (taskId !== this.taskId) return;
			this.view = initialView();
			this.stopping = status.aborting;
			this.status = 'attaching';
			this.#attach(taskId);
		} catch {
			if (taskId !== this.taskId) return;
			this.#events?.close();
			this.#events = null;
			this.#resetPrompt();
			this.status = 'interrupted';
		}
	}

	#resetPrompt() {
		this.sending = false;
		this.fieldError = null;
		this.sendError = null;
	}

	#clear() {
		this.#events?.close();
		this.#events = null;
		this.#reattaches = 0;
		this.taskId = null;
		this.kind = null;
		this.#discoveryInstance = null;
		this.view = initialView();
		this.stopping = false;
		this.seen = false;
		this.status = 'idle';
		this.#resetPrompt();
	}
}

/** The one store of the app. */
export const sync = new SyncStore();

/** What the entry points ("Fetch", "Run again") need: the plan read, the store's start, and where to go. */
export function entryDeps(go: EntryDeps['go']): EntryDeps {
	return { readPlan: () => readSyncPlan(), start: (items) => sync.start(items), go };
}
