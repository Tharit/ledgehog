// Pure helpers of the review queue's rows (patterns §7): paging appends without duplicates, and
// patching replaces entries by id inside the units held, never adding or moving a unit.
import type { Entry } from '#lib/types/domain.js';
import { insertCreated } from './patch.js';
import { formatCount, formatDate } from '#lib/format/index.js';
import type { Lookups } from '#lib/ledger/lookups.js';
import type { Affected, QueueAccountGroup, QueueGroup, Unit } from './types.js';

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

/** The identity of a group of units: a currency (needs an account) or an account (waiting). */
export type GroupKey = string;
export const currencyKey = (currency: string): GroupKey => `currency:${currency}`;
export const accountKey = (accountId: number): GroupKey => `account:${accountId}`;

/** The group a unit is drawn in, or null for a unit in a section without groups. */
export function groupKeyOf(unit: Unit): GroupKey | null {
	if (unit.needs_account) return currencyKey(unit.needs_account.currency);
	if (unit.waiting) return accountKey(unit.waiting.account_id);
	return null;
}

/**
 * The units in the order of the server's groups (currency groups, or account groups of the waiting
 * section; stable within a group, so by date as given). The page shows the groups in this order,
 * and stepping goes through the units in it: what is drawn is what `[` and `]` walk. Units without
 * a group follow, in the order given.
 */
export function orderByGroups(units: readonly Unit[], keys: readonly GroupKey[]): Unit[] {
	const rank = new Map(keys.map((key, i) => [key, i]));
	const of = (u: Unit) => rank.get(groupKeyOf(u) ?? '') ?? keys.length;
	return units
		.map((unit, at) => ({ unit, at }))
		.sort((a, b) => of(a.unit) - of(b.unit) || a.at - b.at)
		.map((x) => x.unit);
}

/** The keys of a section's groups, in the server's order. */
export function groupKeys(section: {
	groups: readonly QueueGroup[];
	accountGroups: readonly QueueAccountGroup[];
}): GroupKey[] {
	return [
		...section.groups.map((g) => currencyKey(g.currency)),
		...section.accountGroups.map((g) => accountKey(g.account_id))
	];
}

/** A group of units under one heading: the units of `key` among `units`, in the order given. */
export function unitsOfGroup(units: readonly Unit[], key: GroupKey): Unit[] {
	return units.filter((u) => groupKeyOf(u) === key);
}

/** "Waiting for Savings, synced through 12 Oct 2026" / "…, not synced yet". */
export function waitingReason(
	waiting: { account_id: number; synced_through: string | null },
	lookups: Lookups,
	locale = 'en'
): string {
	const name = lookups.accounts.get(waiting.account_id)?.name ?? 'another account';
	return waiting.synced_through === null
		? `Waiting for ${name}, not synced yet`
		: `Waiting for ${name}, synced through ${formatDate(waiting.synced_through, locale)}`;
}
