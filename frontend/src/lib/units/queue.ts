// Pure helpers of the review queue's rows (patterns §7): paging appends without duplicates, and
// patching replaces entries by id inside the units held, never adding or moving a unit.
import type { Entry } from '#lib/types/domain.js';
import { insertCreated } from './patch.js';
import { formatCount, formatDate } from '#lib/format/index.js';
import type { Lookups } from '#lib/ledger/lookups.js';
import type { Affected, QueueGroup, Unit } from './types.js';
import { waitingText } from './unit-document.js';

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

/** The units with the entries an action created put into the unit of their anchor (and nowhere else). */
export function insertUnitEntries(units: readonly Unit[], affected: Affected): Unit[] {
	const createdIds = new Set(affected.created ?? []);
	const anchor = affected.anchor_entry_id;
	if (createdIds.size === 0 || anchor === undefined) return [...units];
	const created = affected.entries.filter((e) => createdIds.has(e.id));
	return units.map((unit) =>
		unit.entries.some((e) => e.id === anchor)
			? { ...unit, entries: insertCreated(unit.entries, created, anchor) }
			: unit
	);
}

/** The heading of a needs-an-account group: "3 transfers need an account in USD". */
export function groupHeading(count: number, currency: string, locale = 'en'): string {
	return count === 1
		? `A transfer needs an account in ${currency}`
		: `${formatCount(count, locale)} transfers need an account in ${currency}`;
}

/** The passive notice after an account was added: "3 units can now be completed: refresh". */
export function completableNotice(count: number, locale = 'en'): string {
	return count === 1
		? '1 unit can now be completed: refresh'
		: `${formatCount(count, locale)} units can now be completed: refresh`;
}

/**
 * The units in the order of the server's currency groups (stable within a group, so by date as
 * given). The page shows the groups in this order, and stepping goes through the units in it:
 * what is drawn is what `[` and `]` walk. Units without a group follow, in the order given.
 */
export function orderByGroups(units: readonly Unit[], groups: readonly QueueGroup[]): Unit[] {
	const rank = new Map(groups.map((g, i) => [g.currency, i]));
	const of = (u: Unit) => rank.get(u.needs_account?.currency ?? '') ?? groups.length;
	return units
		.map((unit, at) => ({ unit, at }))
		.sort((a, b) => of(a.unit) - of(b.unit) || a.at - b.at)
		.map((x) => x.unit);
}

/** A group of units under one heading: the groups present among `units`, in the groups' order. */
export function unitsOfGroup(units: readonly Unit[], currency: string): Unit[] {
	return units.filter((u) => u.needs_account?.currency === currency);
}

/** "Waiting for Savings, synced through 12 Oct 2026" / "…, not synced yet". */
export function waitingReason(
	waiting: NonNullable<Unit['waiting']>,
	lookups: Lookups,
	locale = 'en'
): string {
	const name = lookups.accounts.get(waiting.account_id)?.name ?? 'another account';
	return waiting.synced_through === null
		? `Waiting for ${name}, not synced yet`
		: `Waiting for ${name}, synced through ${formatDate(waiting.synced_through, locale)}`;
}

/** "Waiting for the rest of order 302-1 from amazon: 20.00 of 50.00 not yet charged". */
export function waitingOrderReason(
	waiting: NonNullable<Unit['waiting_order']>,
	locale = 'en'
): string {
	return waitingText(waiting, locale);
}

/** "Waiting for a document from amazon, covered through 12 Oct 2026" / "…, not synced yet". */
export function waitingDocumentReason(
	waiting: NonNullable<Unit['waiting_document']>,
	locale = 'en'
): string {
	return waitingText(waiting, locale);
}
