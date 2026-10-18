// What runs for the life of a signed-in session (architecture §4.2, §6.4, §6.5), wired once by the
// root layout: the change watcher, which carries the user's active task to the task store, and the
// Review item's count, read when the first change value is in and whenever the ledger's moves.
// Everything is dropped when the session ends. Call while a component initialises.
import { untrack } from 'svelte';
import { changes, type ChangeWatcher } from './changes.svelte.js';
import { reviewCount, type ReviewCount } from './review-count.svelte.js';
import { session } from './session.svelte.js';
import { sync, type SyncStore } from './sync.svelte.js';

export type LiveDeps = {
	watcher?: ChangeWatcher;
	tasks?: Pick<SyncStore, 'follow' | 'dispose'>;
	count?: Pick<ReviewCount, 'refresh' | 'reset'>;
	signedIn?: () => boolean;
};

export function runLiveData({
	watcher = changes,
	tasks = sync,
	count = reviewCount,
	signedIn = () => session.status === 'authenticated'
}: LiveDeps = {}): void {
	$effect(() => {
		if (!signedIn()) return;
		untrack(() => watcher.start((task) => void tasks.follow(task)));
		return () => {
			watcher.stop();
			tasks.dispose();
			count.reset();
		};
	});
	$effect(() => {
		if (signedIn() && watcher.ledger !== null) untrack(() => void count.refresh());
	});
}
