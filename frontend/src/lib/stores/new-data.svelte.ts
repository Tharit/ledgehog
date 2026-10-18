// How a view meets the change values (architecture §4.2, ux/patterns.md §7). A view that holds a
// snapshot owns a `NewDataWatch` keyed to what it shows: it takes the key's value before it fetches,
// and `stale` says the value has moved since, for the one quiet notice "New data — Refresh". A list
// that is not a snapshot calls `refetchOnChange` and simply fetches again when the ledger's value
// moves. Nothing is counted.
import { untrack } from 'svelte';
import { changes, type ChangeKey, type ChangeWatcher } from './changes.svelte.js';

export class NewDataWatch {
	#key: ChangeKey | null;
	readonly #watcher: ChangeWatcher;
	/** the value the view fetched at; null while the watcher had none yet */
	#seen = $state<string | null>(null);

	/** `key` may be given later (`rekey`): the account page knows its account when it opens. */
	constructor(key: ChangeKey | null = null, watcher: ChangeWatcher = changes) {
		this.#key = key;
		this.#watcher = watcher;
		watcher.register(this);
		this.take();
	}

	/** what the view shows has changed since it last fetched */
	get stale(): boolean {
		const now = this.#now();
		return now !== null && this.#seen !== null && now !== this.#seen;
	}

	/** The view is fetched now: what has changed so far is in it. Call before the request goes out. */
	take(): void {
		this.#seen = this.#now();
	}

	/** The view shows something else (another account): watch its key, fetched now. */
	rekey(key: ChangeKey): void {
		this.#key = key;
		this.take();
	}

	/** The watcher read its first value after the view fetched: that is what the view has. */
	fill(): void {
		if (this.#seen === null) this.#seen = this.#now();
	}

	#now(): string | null {
		return this.#key === null ? null : this.#watcher.valueOf(this.#key);
	}
}

/**
 * Fetch again whenever the value of `key` moves (the ledger's, for every list that is not a
 * snapshot): not on mount, where the page fetches itself, and not for the first value the watcher
 * ever reads. Call while a component initialises.
 */
export function refetchOnChange(
	key: ChangeKey,
	reload: () => void,
	watcher: ChangeWatcher = changes
): void {
	let seen = watcher.valueOf(key);
	$effect(() => {
		const now = watcher.valueOf(key);
		if (now === null || now === seen) return;
		const first = seen === null;
		seen = now;
		if (!first) untrack(reload);
	});
}
