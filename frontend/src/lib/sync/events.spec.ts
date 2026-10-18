import { describe, expect, it } from 'vitest';
import {
	canRunAgain,
	foldAll,
	foldEvent,
	initialView,
	promptItem,
	runAgainItems,
	stuckFailures
} from './events.js';
import {
	ev,
	instanceFailed,
	promptEvent,
	runFailed,
	runFinished,
	runStarted,
	taskEnded,
	taskStarted
} from './fixtures.js';

const start = ev(
	1,
	'task_started',
	taskStarted([
		{ id: 1, accounts: [7, 8, null] },
		{ id: 2, accounts: [9] }
	])
);

describe('foldEvent', () => {
	it('lays out the instances and their items, queued, from task_started', () => {
		const view = foldEvent(initialView(), start);
		expect(view.kind).toBe('sync');
		expect(view.instances.map((i) => [i.instanceId, i.state, i.items.length])).toEqual([
			[1, 'queued', 3],
			[2, 'queued', 1]
		]);
		expect(view.instances[0].items[2]).toMatchObject({ accountId: null, kind: 'documents' });
	});

	it('folds a clean sync', () => {
		const view = foldAll([
			start,
			ev(2, 'instance_started', { instance_id: 1 }),
			ev(3, 'run_started', runStarted(1, 10, 7, '2026-10-08')),
			ev(4, 'run_finished', runFinished(1, 10, 7)),
			ev(5, 'run_started', runStarted(1, 11, 8)),
			ev(6, 'run_finished', runFinished(1, 11, 8)),
			ev(7, 'run_started', runStarted(1, 12, null)),
			ev(8, 'run_finished', runFinished(1, 12, null)),
			ev(9, 'instance_started', { instance_id: 2 }),
			ev(10, 'run_started', runStarted(2, 13, 9)),
			ev(11, 'run_finished', runFinished(2, 13, 9)),
			ev(12, 'task_ended', taskEnded({ ok: 4 }))
		]);
		expect(view.instances.map((i) => i.state)).toEqual(['finished', 'finished']);
		expect(view.instances[0].items.map((i) => i.state)).toEqual(['done', 'done', 'done']);
		expect(view.instances[0].items[0]).toMatchObject({
			runId: 10,
			since: '2026-10-08',
			stats: { inserted: 12, skipped_by_identity: 31 }
		});
		expect(view.end).toEqual({ outcome: 'completed', ok: 4, failed: 0, notStarted: [] });
		expect(view.lastId).toBe(12);
	});

	it('shows a login as signing in, then at work, while a run is fetching', () => {
		const signing = foldAll([start, ev(2, 'instance_started', { instance_id: 1 })]);
		expect(signing.instances[0].state).toBe('signing_in');
		const working = foldEvent(signing, ev(3, 'run_started', runStarted(1, 10, 7)));
		expect(working.instances[0].state).toBe('working');
		expect(working.instances[0].items[0].state).toBe('fetching');
		expect(working.instances[0].items[1].state).toBe('queued');
	});

	it('fails one item without failing the login', () => {
		const view = foldAll([
			start,
			ev(2, 'instance_started', { instance_id: 1 }),
			ev(3, 'run_started', runStarted(1, 10, 7)),
			ev(4, 'run_failed', runFailed(1, 10, 7)),
			ev(5, 'run_started', runStarted(1, 11, 8)),
			ev(6, 'run_finished', runFinished(1, 11, 8))
		]);
		const [first, second] = view.instances[0].items;
		expect(first).toMatchObject({
			state: 'failed',
			failure: { code: 'parse_failed', retryable: false }
		});
		expect(second.state).toBe('done');
		expect(view.instances[0].failure).toBeNull();
	});

	it('fails a login at sign-in: its error once, every item not fetched', () => {
		const view = foldAll([
			start,
			ev(2, 'instance_started', { instance_id: 1 }),
			ev(3, 'instance_failed', instanceFailed(1, { run_ids: [10, 11, 12] }))
		]);
		const [instance] = view.instances;
		expect(instance.state).toBe('failed');
		expect(instance.failure).toMatchObject({ retryable: true });
		expect(instance.items.map((i) => i.state)).toEqual([
			'not_fetched',
			'not_fetched',
			'not_fetched'
		]);
	});

	it('ends a login early: what was done stays, the rest is not fetched', () => {
		const view = foldAll([
			start,
			ev(2, 'instance_started', { instance_id: 1 }),
			ev(3, 'run_started', runStarted(1, 10, 7)),
			ev(4, 'run_finished', runFinished(1, 10, 7)),
			ev(5, 'run_started', runStarted(1, 11, 8)),
			ev(6, 'instance_failed', instanceFailed(1, { run_ids: [11, 12] }))
		]);
		expect(view.instances[0].items.map((i) => i.state)).toEqual([
			'done',
			'not_fetched',
			'not_fetched'
		]);
	});

	it('marks the logins an abort did not reach, and clears the prompt', () => {
		const view = foldAll([
			start,
			ev(2, 'instance_started', { instance_id: 1 }),
			ev(3, 'prompt', promptEvent(1, null)),
			ev(4, 'prompt_resolved', { prompt_id: 'p1', outcome: 'aborted' }),
			ev(5, 'instance_failed', instanceFailed(1, { code: 'challenge_abandoned' })),
			ev(6, 'task_ended', taskEnded({ outcome: 'aborted', failed: 3, not_started: [2] }))
		]);
		expect(view.instances.map((i) => i.state)).toEqual(['failed', 'not_started']);
		expect(view.end?.outcome).toBe('aborted');
		expect(view.end?.notStarted).toEqual([2]);
		expect(view.prompt).toBeNull();
	});

	it('opens a prompt on `prompt` and closes it on its `prompt_resolved`', () => {
		const open = foldAll([
			start,
			ev(2, 'instance_started', { instance_id: 1 }),
			ev(3, 'prompt', promptEvent(1, null))
		]);
		expect(open.prompt).toMatchObject({ promptId: 'p1', instanceId: 1, runId: null });
		const other = foldEvent(
			open,
			ev(4, 'prompt_resolved', { prompt_id: 'zzz', outcome: 'answered' })
		);
		expect(other.prompt).not.toBeNull();
		const closed = foldEvent(
			other,
			ev(5, 'prompt_resolved', { prompt_id: 'p1', outcome: 'answered' })
		);
		expect(closed.prompt).toBeNull();
	});

	it('finds the item a prompt of a run belongs to', () => {
		const view = foldAll([
			start,
			ev(2, 'instance_started', { instance_id: 1 }),
			ev(3, 'run_started', runStarted(1, 10, 7)),
			ev(4, 'prompt', promptEvent(1, 10, { kind: 'text', subject: 'tan_medium_name' }))
		]);
		expect(promptItem(view)?.accountId).toBe(7);
	});

	it('replays a resolved prompt, which has no body, as nothing open', () => {
		const view = foldAll([
			start,
			ev(2, 'instance_started', { instance_id: 1 }),
			ev(3, 'prompt', promptEvent(1, null, null)),
			ev(4, 'prompt_resolved', { prompt_id: 'p1', outcome: 'answered' }),
			ev(5, 'run_started', runStarted(1, 10, 7))
		]);
		expect(view.prompt).toBeNull();
		expect(view.instances[0].items[0].state).toBe('fetching');
	});

	it('rebuilds a still open prompt from a replay', () => {
		const view = foldAll([
			start,
			ev(2, 'instance_started', { instance_id: 1 }),
			ev(3, 'prompt', promptEvent(1, null))
		]);
		expect(view.prompt?.body).toEqual({ kind: 'secret', subject: 'pin' });
		expect(view.end).toBeNull();
	});

	it('ignores events at or below the last id seen', () => {
		const once = foldAll([start, ev(2, 'instance_started', { instance_id: 1 })]);
		const again = foldAll(
			[
				start,
				ev(2, 'instance_started', { instance_id: 1 }),
				ev(3, 'run_started', runStarted(1, 10, 7))
			],
			once
		);
		expect(again.instances[0].items[0].state).toBe('fetching');
		expect(foldEvent(again, ev(3, 'run_failed', runFailed(1, 10, 7)))).toBe(again);
		expect(again.lastId).toBe(3);
	});

	it('does not mutate the view it folds into', () => {
		const before = foldEvent(initialView(), start);
		const snapshot = JSON.stringify(before);
		foldEvent(before, ev(2, 'instance_started', { instance_id: 1 }));
		expect(JSON.stringify(before)).toBe(snapshot);
	});
});

describe('what a failed login offers', () => {
	const failedAt = (over: Parameters<typeof instanceFailed>[1]) =>
		foldAll([
			start,
			ev(2, 'instance_started', { instance_id: 1 }),
			ev(3, 'run_started', runStarted(1, 10, 7)),
			ev(4, 'run_finished', runFinished(1, 10, 7)),
			ev(5, 'instance_failed', instanceFailed(1, over))
		]).instances[0];

	it('offers "Run again" for a retryable login, covering what did not finish', () => {
		const instance = failedAt({ retryable: true });
		expect(canRunAgain(instance)).toBe(true);
		expect(runAgainItems(instance)).toEqual([
			{ instance_id: 1, account_id: 8 },
			{ instance_id: 1, kind: 'documents' }
		]);
		expect(stuckFailures(instance)).toEqual([]);
	});

	it('offers nothing to run for a login trying again cannot help, and lists its failure once', () => {
		const instance = failedAt({ retryable: false, code: 'bank_setup_required' });
		expect(canRunAgain(instance)).toBe(false);
		expect(stuckFailures(instance)).toHaveLength(1);
	});

	it('leaves an item that trying again cannot help out of "Run again"', () => {
		const view = foldAll([
			start,
			ev(2, 'instance_started', { instance_id: 1 }),
			ev(3, 'run_started', runStarted(1, 10, 7)),
			ev(4, 'run_failed', runFailed(1, 10, 7, { retryable: false })),
			ev(5, 'run_started', runStarted(1, 11, 8)),
			ev(6, 'run_failed', runFailed(1, 11, 8, { retryable: true, code: 'source_unavailable' }))
		]);
		const [instance] = view.instances;
		expect(canRunAgain(instance)).toBe(true);
		expect(runAgainItems(instance)).toEqual([
			{ instance_id: 1, account_id: 8 },
			{ instance_id: 1, kind: 'documents' }
		]);
		expect(stuckFailures(instance)).toHaveLength(1);
	});

	it('offers nothing for a login that went through', () => {
		const view = foldAll([
			start,
			ev(2, 'instance_started', { instance_id: 2 }),
			ev(3, 'run_started', runStarted(2, 13, 9)),
			ev(4, 'run_finished', runFinished(2, 13, 9))
		]);
		expect(canRunAgain(view.instances[1])).toBe(false);
	});
});
