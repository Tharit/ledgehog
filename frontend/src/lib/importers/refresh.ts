// "Refresh accounts" as an entry point (ux/views/importers.md): the instance list's icon action and
// the instance page's linked-accounts action both start the discovery and open its page. A refused
// start stays where the user is, as a notice; a busy one links to the task that is running.
import { isBusyRefusal, refusalText, type StartRefusal } from '#lib/sync/entry.js';
import { discoveryUrl } from './links.js';

export type RefreshDeps = {
	start: (instanceId: number) => Promise<StartRefusal | null>;
	go: (path: string) => void | Promise<void>;
};

/** Start the discovery of an instance and open its page; the refusal, if any, for the caller to show. */
export async function startRefresh(
	instanceId: number,
	deps: RefreshDeps
): Promise<StartRefusal | null> {
	const refusal = await deps.start(instanceId);
	if (refusal) return refusal;
	await deps.go(discoveryUrl(instanceId));
	return null;
}

/** What a refused start says, and where the running task is when that is the reason. */
export function refreshNotice(
	refusal: StartRefusal,
	runningPath: string
): { text: string; error: boolean; action?: { label: string; path: string } } {
	return isBusyRefusal(refusal)
		? {
				text: refusalText(refusal),
				error: false,
				action: { label: 'Open the running task', path: runningPath }
			}
		: { text: refusalText(refusal), error: true };
}
