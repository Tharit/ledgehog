// Test fixtures for the sync screens: events as the stream delivers them, and plan reads.
import type { PlanInstance, PromptBody, SyncEvent, SyncEventPayloads } from '#lib/api/sync.js';

type Payload<N extends keyof SyncEventPayloads> = SyncEventPayloads[N];

/** An event at an id; ids are given by the caller so a test can replay or repeat them. */
export function ev<N extends keyof SyncEventPayloads>(
	id: number,
	name: N,
	data: Payload<N>
): SyncEvent {
	return { id, name, data } as SyncEvent;
}

export const taskStarted = (
	instances: { id: number; accounts: (number | null)[] }[],
	kind: 'sync' | 'discovery' = 'sync'
): Payload<'task_started'> => ({
	kind,
	instances: instances.map((i) => ({
		instance_id: i.id,
		items: i.accounts.map((account) => ({
			account_id: account,
			kind: account === null ? ('documents' as const) : ('transactions' as const)
		}))
	}))
});

export const runStarted = (
	instance: number,
	run: number,
	account: number | null,
	since = '2026-10-01'
): Payload<'run_started'> => ({
	instance_id: instance,
	run_id: run,
	account_id: account,
	kind: account === null ? 'documents' : 'transactions',
	since
});

export const runFinished = (
	instance: number,
	run: number,
	account: number | null,
	stats: Record<string, unknown> = { inserted: 12, skipped_by_identity: 31 }
): Payload<'run_finished'> => ({
	instance_id: instance,
	run_id: run,
	account_id: account,
	kind: account === null ? 'documents' : 'transactions',
	stats
});

export const runFailed = (
	instance: number,
	run: number,
	account: number | null,
	over: Partial<Payload<'run_failed'>> = {}
): Payload<'run_failed'> => ({
	instance_id: instance,
	run_id: run,
	account_id: account,
	kind: account === null ? 'documents' : 'transactions',
	code: 'parse_failed',
	message: 'ParseFailed: the format changed',
	retryable: false,
	...over
});

export const instanceFailed = (
	instance: number,
	over: Partial<Payload<'instance_failed'>> = {}
): Payload<'instance_failed'> => ({
	instance_id: instance,
	code: 'source_unavailable',
	message: 'SourceUnavailable: the bank did not answer',
	retryable: true,
	run_ids: [],
	...over
});

export const taskEnded = (over: Partial<Payload<'task_ended'>> = {}): Payload<'task_ended'> => ({
	outcome: 'completed',
	ok: 0,
	failed: 0,
	not_started: [],
	...over
});

export const secretPrompt: PromptBody = { kind: 'secret', subject: 'pin' };

export const promptEvent = (
	instance: number,
	run: number | null,
	body: PromptBody | null = secretPrompt,
	promptId = 'p1'
): Payload<'prompt'> => ({
	prompt_id: promptId,
	instance_id: instance,
	run_id: run,
	expires_at: '2026-10-18T10:05:00Z',
	prompt: body
});

export function planInstance(over: Partial<PlanInstance> = {}): PlanInstance {
	return {
		instance_id: 1,
		importer: 'testfetch',
		label: 'Giro login',
		busy: false,
		documents_since: null,
		accounts: [
			{
				account_id: 7,
				external_ref: 'ref-7',
				since: '2026-10-08',
				since_source: 'coverage',
				editable: false
			}
		],
		...over
	};
}
