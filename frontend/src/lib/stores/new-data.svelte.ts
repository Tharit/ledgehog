// How a view meets the sync store's revisions (architecture §6.4, ux/views/sync.md "New data").
// A view that holds a snapshot owns a `NewDataWatch`: it takes the revision when it fetches, and
// `stale` says that rows arrived since, for the one quiet notice. A list that is not a snapshot
// calls `refetchOnSyncEnd` and simply fetches again when a sync ends. Nothing is counted.
import { untrack } from 'svelte';
import { sync } from './sync.svelte.js';

/** The part of the sync store a view reads (a test passes its own). */
export type Revisions = { readonly dataRevision: number; readonly endRevision: number };

export class NewDataWatch {
	readonly #source: Revisions;
	#seen = $state(0);

	constructor(source: Revisions = sync) {
		this.#source = source;
		this.#seen = source.dataRevision;
	}

	/** rows arrived from a sync since the view last fetched */
	get stale(): boolean {
		return this.#source.dataRevision > this.#seen;
	}

	/** The view is fetched now: what has arrived so far is in it. Call before the request goes out. */
	take(): void {
		this.#seen = this.#source.dataRevision;
	}
}

/**
 * Fetch again whenever a sync ends (not on mount: the page fetches then itself). Call while a
 * component initialises.
 */
export function refetchOnSyncEnd(reload: () => void, source: Revisions = sync): void {
	let seen = source.endRevision;
	$effect(() => {
		const now = source.endRevision;
		if (now === seen) return;
		seen = now;
		untrack(reload);
	});
}
