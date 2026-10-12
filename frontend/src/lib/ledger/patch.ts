// Patching the rows a list holds after a tag write (patterns §7): pure functions over plain
// values, so the store only assigns the results. Rows are never added, removed or reordered.
import type { Entry, EntryTagIds } from '#lib/types/domain.js';

export const NO_IDS: ReadonlySet<number> = new Set();

/** The entries with the given tag ids written into their rows; same rows, same order. */
export function patchTagIds(entries: readonly Entry[], updates: readonly EntryTagIds[]): Entry[] {
	const byId = new Map(updates.map((u) => [u.id, u.tag_ids]));
	return entries.map((entry) => {
		const tag_ids = byId.get(entry.id);
		return tag_ids ? { ...entry, tag_ids } : entry;
	});
}

/** `ids` joined to the set of entries touched so far. */
export function withIds(touched: ReadonlySet<number>, ids: Iterable<number>): ReadonlySet<number> {
	return new Set([...touched, ...ids]);
}

/**
 * The touched rows that an active tag filter (`wanted`, OR) no longer matches: they stay where
 * they are and are marked until the list is refreshed (decision C10).
 */
export function rowsOutOfTagFilter(
	entries: readonly Entry[],
	touched: ReadonlySet<number>,
	wanted: readonly number[]
): ReadonlySet<number> {
	if (wanted.length === 0 || touched.size === 0) return NO_IDS;
	return new Set(
		entries
			.filter((e) => touched.has(e.id) && !e.tag_ids.some((id) => wanted.includes(id)))
			.map((e) => e.id)
	);
}
