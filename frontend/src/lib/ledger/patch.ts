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

/** The ids of the held rows whose tags differ in `fresh` (a commit of the unit panel changed them). */
export function tagChangedIds(entries: readonly Entry[], fresh: readonly Entry[]): number[] {
	const held = new Map(entries.map((e) => [e.id, e]));
	return fresh.flatMap((e) => {
		const before = held.get(e.id);
		if (!before) return [];
		const same =
			before.tag_ids.length === e.tag_ids.length &&
			before.tag_ids.every((t) => e.tag_ids.includes(t));
		return same ? [] : [e.id];
	});
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

/** Tooltip of a row marked after the user's own tag action took it out of the tag filter. */
export const CHANGED_BY_YOU = 'changed by your last action';
/** Tooltip of a row a refresh in place did not return. */
export const CHANGED_ELSEWHERE = 'no longer matches, or changed elsewhere';

/** The ids of these entries. */
export function idsOf(entries: readonly Entry[]): ReadonlySet<number> {
	return new Set(entries.map((e) => e.id));
}

/** The moved marks after a refresh: rows the answer returned are cleared, `missing` ones added. */
export function nextMoved(
	moved: ReadonlySet<number>,
	fresh: readonly Entry[],
	missing: ReadonlySet<number>
): ReadonlySet<number> {
	const returned = idsOf(fresh);
	return new Set([...[...moved].filter((id) => !returned.has(id)), ...missing]);
}

/**
 * Merge a refetched window into the rows held, by id: held rows the answer contains are replaced
 * by the fresh row; held rows it does not contain are kept, and named in `missing`. Rows only in
 * the answer are not added. Same rows, same order (§7). Only `held` ids count as missing, so rows
 * that arrived after the request was made are left alone.
 */
export function mergeRefreshed(
	entries: readonly Entry[],
	fresh: readonly Entry[],
	held: ReadonlySet<number>
): { entries: Entry[]; missing: ReadonlySet<number> } {
	const byId = new Map(fresh.map((e) => [e.id, e]));
	const missing = new Set<number>();
	const merged = entries.map((entry) => {
		const next = byId.get(entry.id);
		if (next) return next;
		if (held.has(entry.id)) missing.add(entry.id);
		return entry;
	});
	return { entries: merged, missing };
}
