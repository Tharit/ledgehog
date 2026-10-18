// The entry points that sync one thing (ux/views/sync.md "Starting"): "Fetch" on an account's source
// and "Run again" on a failed fetch. Both are one-item syncs: started at once, then the sync page
// shows the progress; only an account without coverage opens the plan narrowed to it first, because
// its start is the one thing the user is asked (spec §5.4).
import { ApiError } from '#lib/api/http.js';
import type { PlanInstance, SyncItem } from '#lib/api/sync.js';
import { narrowedPlanUrl } from './plan.js';

/** A start that did not happen, with the server's code (route on the code, never the message). */
export type StartRefusal = { code: string; message: string };

export function refusalOf(error: unknown): StartRefusal {
	if (error instanceof ApiError) return { code: error.code, message: error.message };
	return { code: 'network_error', message: 'The server could not be reached.' };
}

/** Another sync holds the user or the login: the page says so and links to the sync page. */
export function isBusyRefusal(refusal: StartRefusal): boolean {
	return refusal.code === 'task_active' || refusal.code === 'instance_busy';
}

export const SYNC_RUNNING_TEXT = 'A sync is already running';

/** What a refused start says: the sync being busy in our words, anything else as the server put it. */
export function refusalText(refusal: StartRefusal): string {
	return refusal.code === 'task_active' ? SYNC_RUNNING_TEXT : refusal.message;
}

/** What to fetch: an account of an instance, or the instance's documents. */
export type FetchTarget = { instanceId: number; accountId: number | null };

export type EntryDeps = {
	readPlan: () => Promise<PlanInstance[]>;
	start: (items: SyncItem[]) => Promise<StartRefusal | null>;
	go: (path: string) => void | Promise<void>;
};

/** The item of a target: the account's transactions, or (no account) the documents of the instance. */
export function itemOf(target: FetchTarget): SyncItem {
	return target.accountId === null
		? { instance_id: target.instanceId, kind: 'documents' }
		: { instance_id: target.instanceId, account_id: target.accountId };
}

/**
 * Start one item at once and open the sync page, or open the plan narrowed to it where its start is
 * editable. A start that is refused is returned for the page the user is on to show.
 */
export async function startOrReview(
	target: FetchTarget,
	deps: EntryDeps
): Promise<StartRefusal | null> {
	if (target.accountId !== null) {
		let plan: PlanInstance[];
		try {
			plan = await deps.readPlan();
		} catch (error) {
			return refusalOf(error);
		}
		const account = plan
			.find((i) => i.instance_id === target.instanceId)
			?.accounts.find((a) => a.account_id === target.accountId);
		if (account?.editable) {
			await deps.go(narrowedPlanUrl(target.instanceId, target.accountId));
			return null;
		}
	}
	const refusal = await deps.start([itemOf(target)]);
	if (refusal) return refusal;
	await deps.go('/sync');
	return null;
}
