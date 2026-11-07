// The view of a task as a pure function of the events seen (architecture §6.4): a live stream and a
// replay from id 1 give the same screen. `foldEvent` does no I/O and never mutates; events with an
// id at or below the last one seen are ignored, so a re-created stream can replay into any view.
import type { PromptBody, SyncEvent, SyncItem, TaskKind } from '#lib/api/sync.js';

export type Failure = { code: string; message: string; retryable: boolean };

/** An item is a run: one account's transactions, or an instance's documents. */
export type ItemState = 'queued' | 'fetching' | 'done' | 'failed' | 'not_fetched';

export type TaskItem = {
	accountId: number | null;
	kind: 'transactions' | 'documents';
	state: ItemState;
	runId: number | null;
	/** the start the run began from, once it began */
	since: string | null;
	/** how far the run has got, where its importer says; null until it does */
	progress: { done: number; total: number } | null;
	/** the stored statistics of a finished run, as the event carries them */
	stats: Record<string, unknown> | null;
	failure: Failure | null;
};

/** A login: waiting, signing in, at work, through, failed (its error once), or never reached. */
export type InstanceState =
	'queued' | 'signing_in' | 'working' | 'finished' | 'failed' | 'not_started';

export type TaskInstance = {
	instanceId: number;
	state: InstanceState;
	items: TaskItem[];
	failure: Failure | null;
};

/** The one prompt that is open. A prompt is open if and only if this is set. */
export type OpenPrompt = {
	promptId: string;
	instanceId: number;
	/** null while signing in */
	runId: number | null;
	expiresAt: string;
	body: PromptBody;
};

export type TaskEnd = {
	outcome: 'completed' | 'aborted' | 'abandoned' | 'crashed';
	ok: number;
	failed: number;
	/** the logins never reached */
	notStarted: number[];
};

export type TaskView = {
	kind: TaskKind | null;
	/** the id of the last event folded in */
	lastId: number;
	instances: TaskInstance[];
	prompt: OpenPrompt | null;
	end: TaskEnd | null;
};

export function initialView(): TaskView {
	return { kind: null, lastId: 0, instances: [], prompt: null, end: null };
}

function mapInstance(
	view: TaskView,
	instanceId: number,
	change: (instance: TaskInstance) => TaskInstance
): TaskInstance[] {
	return view.instances.map((i) => (i.instanceId === instanceId ? change(i) : i));
}

function mapItem(
	instance: TaskInstance,
	match: { runId: number; accountId: number | null; kind: TaskItem['kind'] },
	change: (item: TaskItem) => TaskItem
): TaskInstance {
	// the run's own item once it began; before that, the first queued item of the same account and kind
	let index = instance.items.findIndex((i) => i.runId === match.runId);
	if (index < 0) {
		index = instance.items.findIndex(
			(i) => i.state === 'queued' && i.accountId === match.accountId && i.kind === match.kind
		);
	}
	if (index < 0) return instance;
	const items = instance.items.map((item, at) => (at === index ? change(item) : item));
	// a login whose items have all ended is through (there is no event for it)
	const through = items.every((i) => i.state !== 'queued' && i.state !== 'fetching');
	return { ...instance, items, state: through ? 'finished' : instance.state };
}

/** The events that end an instance's items early: what has not finished is "not fetched". */
function unfinished(item: TaskItem): TaskItem {
	return item.state === 'queued' || item.state === 'fetching'
		? { ...item, state: 'not_fetched' }
		: item;
}

export function foldEvent(view: TaskView, event: SyncEvent): TaskView {
	if (event.id <= view.lastId) return view;
	const next = (change: Partial<TaskView>): TaskView => ({ ...view, ...change, lastId: event.id });

	switch (event.name) {
		case 'task_started':
			return next({
				kind: event.data.kind,
				instances: event.data.instances.map((i) => ({
					instanceId: i.instance_id,
					state: 'queued',
					failure: null,
					items: i.items.map((item) => ({
						accountId: item.account_id,
						kind: item.kind,
						state: 'queued',
						runId: null,
						since: null,
						progress: null,
						stats: null,
						failure: null
					}))
				}))
			});

		case 'instance_started':
			return next({
				instances: mapInstance(view, event.data.instance_id, (i) => ({ ...i, state: 'signing_in' }))
			});

		case 'run_started': {
			const d = event.data;
			return next({
				instances: mapInstance(view, d.instance_id, (instance) =>
					mapItem(
						{ ...instance, state: 'working' },
						{ runId: d.run_id, accountId: d.account_id, kind: d.kind },
						(item) => ({ ...item, state: 'fetching', runId: d.run_id, since: d.since })
					)
				)
			});
		}

		case 'run_progress': {
			const d = event.data;
			const progress = { done: d.done, total: d.total };
			// the event names a run, not its login: find the item that began it
			return next({
				instances: view.instances.map((instance) =>
					instance.items.some((i) => i.runId === d.run_id)
						? {
								...instance,
								items: instance.items.map((item) =>
									item.runId === d.run_id && item.state === 'fetching'
										? { ...item, progress }
										: item
								)
							}
						: instance
				)
			});
		}

		case 'prompt': {
			const d = event.data;
			// a replayed prompt that has been resolved has no body: nothing is open
			if (!d.prompt) return next({});
			return next({
				prompt: {
					promptId: d.prompt_id,
					instanceId: d.instance_id,
					runId: d.run_id,
					expiresAt: d.expires_at,
					body: d.prompt
				}
			});
		}

		case 'prompt_resolved':
			return next({
				prompt: view.prompt?.promptId === event.data.prompt_id ? null : view.prompt
			});

		case 'run_finished': {
			const d = event.data;
			return next({
				instances: mapInstance(view, d.instance_id, (instance) =>
					mapItem(instance, { runId: d.run_id, accountId: d.account_id, kind: d.kind }, (item) => ({
						...item,
						state: 'done',
						runId: d.run_id,
						stats: d.stats,
						failure: null
					}))
				)
			});
		}

		case 'run_failed': {
			const d = event.data;
			return next({
				instances: mapInstance(view, d.instance_id, (instance) =>
					mapItem(instance, { runId: d.run_id, accountId: d.account_id, kind: d.kind }, (item) => ({
						...item,
						state: 'failed',
						runId: d.run_id,
						failure: { code: d.code, message: d.message, retryable: d.retryable }
					}))
				)
			});
		}

		case 'instance_failed': {
			const d = event.data;
			return next({
				instances: mapInstance(view, d.instance_id, (instance) => ({
					...instance,
					state: 'failed',
					failure: { code: d.code, message: d.message, retryable: d.retryable },
					items: instance.items.map(unfinished)
				}))
			});
		}

		case 'task_ended': {
			const d = event.data;
			const notStarted = new Set(d.not_started);
			return next({
				prompt: null,
				end: { outcome: d.outcome, ok: d.ok, failed: d.failed, notStarted: d.not_started },
				instances: view.instances.map((i) =>
					notStarted.has(i.instanceId)
						? { ...i, state: 'not_started' }
						: i.state === 'signing_in' || i.state === 'working'
							? { ...i, state: 'finished', items: i.items.map(unfinished) }
							: i
				)
			});
		}
	}
}

/** The events of a replay, folded in order into a fresh view. */
export function foldAll(events: readonly SyncEvent[], from: TaskView = initialView()): TaskView {
	return events.reduce(foldEvent, from);
}

// ---- what the view says -----------------------------------------------------------------------

/** The items of a login that a "Run again" fetches: all that did not finish, except what cannot be helped by trying. */
export function runAgainItems(instance: TaskInstance): SyncItem[] {
	return instance.items
		.filter((item) => item.state !== 'done' && !(item.failure && !item.failure.retryable))
		.map((item) =>
			item.kind === 'documents'
				? { instance_id: instance.instanceId, kind: 'documents' as const }
				: { instance_id: instance.instanceId, account_id: item.accountId }
		);
}

/** Whether a "Run again" is offered: a failure of this login that trying again can help. */
export function canRunAgain(instance: TaskInstance): boolean {
	if (instance.failure) return instance.failure.retryable && runAgainItems(instance).length > 0;
	return (
		instance.items.some((i) => i.state === 'failed' && i.failure?.retryable === true) &&
		runAgainItems(instance).length > 0
	);
}

/** The failures of a login that trying again cannot help, each once (the instance's, else its items'). */
export function stuckFailures(instance: TaskInstance): Failure[] {
	if (instance.failure) return instance.failure.retryable ? [] : [instance.failure];
	return instance.items.flatMap((i) => (i.failure && !i.failure.retryable ? [i.failure] : []));
}

/** Where the open prompt belongs: the item of its run, or the login while it is signing in. */
export function promptItem(view: TaskView): TaskItem | null {
	const prompt = view.prompt;
	if (!prompt || prompt.runId === null) return null;
	return (
		view.instances
			.find((i) => i.instanceId === prompt.instanceId)
			?.items.find((i) => i.runId === prompt.runId) ?? null
	);
}
