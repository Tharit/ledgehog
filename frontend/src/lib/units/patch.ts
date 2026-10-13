// Patching the rows a list holds after an action (patterns §7), as pure functions: replace by id,
// never add, remove or reorder, and say what changed with marks. Rows the user's action resolved
// are marked resolved; rows that changed state as a consequence are marked differently; refreshed
// proposals are patched silently (a commit can refresh dozens). The one exception to "never add":
// the entries a split creates are inserted next to their anchor (`insertCreated`).
import type { Entry } from '#lib/types/domain.js';
import type { Affected } from './types.js';

export type Marks = {
	/** rows the user's action resolved */
	resolved: ReadonlyMap<number, string>;
	/** rows that changed state as a consequence of it */
	consequence: ReadonlyMap<number, string>;
	/** rows that no longer exist: kept and marked */
	deleted: ReadonlyMap<number, string>;
	/** rows that returned to review */
	returnedToReview: ReadonlyMap<number, string>;
};

export const MARK_RESOLVED = 'resolved by your last action';
export const MARK_CONSEQUENCE = 'changed by your last action';
export const MARK_DELETED = 'deleted by your last action';
export const MARK_RETURNED = 'returned to review by your last action';

export function noMarks(): Marks {
	return {
		resolved: new Map(),
		consequence: new Map(),
		deleted: new Map(),
		returnedToReview: new Map()
	};
}

/** Does the row carry the same review state (its flags) as before? */
function sameState(a: Entry, b: Entry): boolean {
	return (
		a.review_flags.length === b.review_flags.length &&
		a.review_flags.every((flag) => b.review_flags.includes(flag))
	);
}

/**
 * The entries a split created, inserted next to their anchor: after the anchor's row and the rows
 * that follow it in the same unit, so the unit stays together. Entries the list holds are not
 * inserted again; when the list holds neither the anchor nor a row of the unit nothing is added.
 */
export function insertCreated(
	entries: readonly Entry[],
	created: readonly Entry[],
	anchorId: number
): Entry[] {
	const held = new Set(entries.map((e) => e.id));
	const fresh = created.filter((e) => !held.has(e.id)).sort((a, b) => a.id - b.id);
	if (fresh.length === 0) return [...entries];
	let at = entries.findIndex((e) => e.id === anchorId);
	if (at < 0) {
		const key = fresh[0].unit_key;
		at = key === null ? -1 : entries.findIndex((e) => e.unit_key === key);
	}
	if (at < 0) return [...entries];
	const key = entries[at].unit_key;
	let end = at + 1;
	while (key !== null && end < entries.length && entries[end].unit_key === key) end++;
	return [...entries.slice(0, end), ...fresh, ...entries.slice(end)];
}

/**
 * The rows with the affected entries written in, and the marks to add to `prior`. Only rows the
 * list holds are touched, except the entries the action created, which are inserted next to
 * their anchor. A held row that is not a user-resolved or returned one is marked as a
 * consequence only when its review state changed.
 */
export function applyAffected(
	entries: readonly Entry[],
	affected: Affected,
	prior: Marks = noMarks()
): { entries: Entry[]; marks: Marks } {
	const fresh = new Map(affected.entries.map((e) => [e.id, e]));
	const createdIds = new Set(affected.created ?? []);
	const rows =
		createdIds.size > 0 && affected.anchor_entry_id !== undefined
			? insertCreated(
					entries,
					affected.entries.filter((e) => createdIds.has(e.id)),
					affected.anchor_entry_id
				)
			: entries;
	const held = new Map(rows.map((e) => [e.id, e]));
	const resolved = new Map(prior.resolved);
	const consequence = new Map(prior.consequence);
	const deleted = new Map(prior.deleted);
	const returnedToReview = new Map(prior.returnedToReview);

	const resolvedIds = new Set(affected.resolved ?? []);
	const returnedIds = new Set(affected.returned_to_review ?? []);
	for (const id of affected.removed_entry_ids ?? []) {
		if (held.has(id)) deleted.set(id, MARK_DELETED);
	}
	for (const [id, next] of fresh) {
		const before = held.get(id);
		if (!before) continue;
		if (resolvedIds.has(id)) resolved.set(id, MARK_RESOLVED);
		else if (returnedIds.has(id)) returnedToReview.set(id, MARK_RETURNED);
		else if (!sameState(before, next)) consequence.set(id, MARK_CONSEQUENCE);
	}

	return {
		entries: rows.map((entry) => fresh.get(entry.id) ?? entry),
		marks: { resolved, consequence, deleted, returnedToReview }
	};
}

/** The marks without those of rows the cursor has visited (a mark fades when the cursor visits). */
export function clearMarks(marks: Marks, id: number): Marks {
	const marked =
		marks.resolved.has(id) ||
		marks.consequence.has(id) ||
		marks.deleted.has(id) ||
		marks.returnedToReview.has(id);
	if (!marked) return marks;
	const without = (map: ReadonlyMap<number, string>) => {
		if (!map.has(id)) return map;
		const next = new Map(map);
		next.delete(id);
		return next;
	};
	return {
		resolved: without(marks.resolved),
		consequence: without(marks.consequence),
		deleted: without(marks.deleted),
		returnedToReview: without(marks.returnedToReview)
	};
}

/** The tooltip of a marked row, or undefined. */
export function markOf(marks: Marks, id: number): string | undefined {
	return (
		marks.deleted.get(id) ??
		marks.returnedToReview.get(id) ??
		marks.resolved.get(id) ??
		marks.consequence.get(id)
	);
}
