import { describe, expect, it } from 'vitest';
import { foldAll, initialView, type TaskEnd } from './events.js';
import { ev, promptEvent, taskStarted } from './fixtures.js';
import { endLines, navStatus, type StatusInput } from './status.js';

const withPrompt = foldAll([
	ev(1, 'task_started', taskStarted([{ id: 1, accounts: [7] }])),
	ev(2, 'instance_started', { instance_id: 1 }),
	ev(3, 'prompt', promptEvent(1, null))
]);

function input(over: Partial<StatusInput> = {}): StatusInput {
	return { phase: 'running', kind: 'sync', view: initialView(), seen: false, ...over };
}

const end = (over: Partial<TaskEnd> = {}): TaskEnd => ({
	outcome: 'completed',
	ok: 3,
	failed: 1,
	notStarted: [],
	...over
});

describe('navStatus', () => {
	it('says nothing while nothing happens', () => {
		expect(navStatus(input({ phase: 'idle' }), '/ledger', '/sync')).toBeNull();
	});

	it('says "Syncing…" with a spinner while a sync runs', () => {
		expect(navStatus(input(), '/ledger', '/sync')).toEqual({ text: 'Syncing…', busy: true });
	});

	it('says "Refreshing accounts…" for a discovery', () => {
		expect(navStatus(input({ kind: 'discovery' }), '/ledger', '/settings/importers/1/accounts')).toEqual(
			{ text: 'Refreshing accounts…', busy: true }
		);
	});

	it('says "Needs your input" when a prompt is open and the task page is not shown', () => {
		const status = input({ view: withPrompt });
		expect(navStatus(status, '/ledger', '/sync')?.text).toBe('Needs your input');
		expect(navStatus(status, '/sync', '/sync')?.text).toBe('Syncing…');
	});

	it('says how a sync finished, until the sync page is opened', () => {
		const ended = input({
			phase: 'ended',
			view: { ...initialView(), end: end() }
		});
		expect(navStatus(ended, '/ledger', '/sync')).toEqual({
			text: 'Finished · 3 ok, 1 failed',
			busy: false
		});
		expect(navStatus({ ...ended, seen: true }, '/ledger', '/sync')).toBeNull();
	});

	it('leaves out a count that is zero, and says "Stopped" after an abort', () => {
		const ended = (e: TaskEnd) => input({ phase: 'ended', view: { ...initialView(), end: e } });
		expect(navStatus(ended(end({ failed: 0 })), '/x', '/sync')?.text).toBe('Finished · 3 ok');
		expect(navStatus(ended(end({ ok: 0 })), '/x', '/sync')?.text).toBe('Finished · 1 failed');
		expect(navStatus(ended(end({ outcome: 'aborted' })), '/x', '/sync')?.text).toBe('Stopped');
	});

	it('says nothing of an ended discovery', () => {
		expect(
			navStatus(
				input({ phase: 'ended', kind: 'discovery', view: { ...initialView(), end: end() } }),
				'/x',
				'/y'
			)
		).toBeNull();
	});
});

describe('endLines', () => {
	const label = (id: number) => `Login ${id}`;

	it('counts the runs of a completed sync', () => {
		expect(endLines(end(), label)).toEqual(['Finished: 3 runs ok, 1 failed']);
		expect(endLines(end({ ok: 1, failed: 0 }), label)).toEqual(['Finished: 1 run ok']);
	});

	it('says an abort wrote nothing more, and names the logins not reached', () => {
		expect(endLines(end({ outcome: 'aborted', notStarted: [2, 3] }), label)).toEqual([
			'Stopped. Nothing more was written.',
			'Not reached: Login 2, Login 3'
		]);
	});

	it('says a crashed sync failed unexpectedly', () => {
		expect(endLines(end({ outcome: 'crashed' }), label)[0]).toMatch(/failed unexpectedly/);
	});
});
