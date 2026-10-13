// Pure helpers of the review queue's rows (patterns §7): paging appends without duplicates, and
// patching replaces entries by id inside the units held, never adding or moving a unit.
import type { Entry } from '#lib/types/domain.js';
import type { Unit } from './types.js';

/** The units held followed by a further page, leaving out units that are already held. */
export function appendUnits(held: readonly Unit[], more: readonly Unit[]): Unit[] {
	const seen = new Set(held.map((u) => u.anchor_entry_id));
	return [...held, ...more.filter((u) => !seen.has(u.anchor_entry_id))];
}

/** The units with each entry replaced by the row of the same id in `entries`, when there is one. */
export function patchUnitEntries(units: readonly Unit[], entries: readonly Entry[]): Unit[] {
	const byId = new Map(entries.map((e) => [e.id, e]));
	return units.map((unit) => ({ ...unit, entries: unit.entries.map((e) => byId.get(e.id) ?? e) }));
}
