// The panel's blocks grouped by the source transaction they came from (patterns §4.1): a unit
// that spans more than one source (a pair) shows one group per source, each with a header, its
// source strip, its residual block, its splits in the order they were added, and its own "Split
// entry". Pure: it orders and gathers what the views already say. A group is data, so a later
// group that has no entry yet (a counter-leg offer, "created when you commit") can be appended.
import type { Evidence, RuleNames } from './evidence.js';
import { describeKey, keyOf } from './evidence.js';
import { sourceGroups, type SourceGroup } from './describe.js';
import type { Entry, Money } from '#lib/types/domain.js';
import type { EntryView } from './view.js';

export type GroupHeader = {
	accountId: number;
	/** the booked date of the group's entry; null when it has none yet */
	bookedOn: string | null;
	/** what the source transaction said */
	amount: Money | null;
	/** the source is user-authored: a small "Entered by hand" */
	authored: boolean;
};

export type PanelGroup = {
	/** stable across edits: the source's id, else the entry that stands in for it */
	key: string;
	sourceId: number | null;
	header: GroupHeader;
	/** the source strip's data; null when the source is not known */
	strip: SourceGroup | null;
	/** residual first, then the others in the order they were added */
	views: EntryView[];
	/** the stored entry "Split entry" splits: the group's original; null when it cannot be split */
	splitEntryId: number | null;
};

/** The source group (strip data) holding any of these entries. */
function stripOf(strips: readonly SourceGroup[], ids: readonly number[]): SourceGroup | null {
	return strips.find((g) => g.entryIds.some((id) => ids.includes(id))) ?? null;
}

/**
 * The groups of `views` in the order shown: by the booked date of the group (earlier first), ties
 * by the lowest stored entry id; the anchor's group is not special. `entries` are the unit's
 * stored entries (the source of each group's strip and header).
 */
export function groupsOf(views: readonly EntryView[], entries: readonly Entry[]): PanelGroup[] {
	const strips = sourceGroups(entries);
	const byKey = new Map<string, EntryView[]>();
	for (const view of views) {
		const key = view.sourceId !== null ? `source-${view.sourceId}` : `entry-${view.fromEntryId}`;
		const list = byKey.get(key) ?? [];
		list.push(view);
		byKey.set(key, list);
	}
	const groups = [...byKey.entries()].map(([key, members]) => {
		// the residual leads; the rest keep the order they came in (stored, then added)
		const ordered = [...members.filter((v) => v.original), ...members.filter((v) => !v.original)];
		const lead = ordered[0];
		const stored = ordered.filter((v) => !v.isNew);
		const storedIds = stored.map((v) => v.id);
		const strip = stripOf(strips, storedIds);
		const date = (v: EntryView) => v.row?.booked_on ?? v.stored?.booked_on ?? null;
		const dated = stored.find((v) => date(v) !== null) ?? lead;
		const original = ordered.find((v) => v.original && !v.isNew);
		const group: PanelGroup = {
			key,
			sourceId: lead.sourceId,
			header: {
				accountId: (original ?? lead).accountId,
				bookedOn: date(dated),
				amount:
					stored.find((v) => v.stored?.source)?.stored?.source?.amount ??
					lead.sourceAmount ??
					(original ?? lead).amount,
				authored: strip?.authored ?? stored.some((v) => v.stored?.authored)
			},
			strip,
			views: ordered,
			splitEntryId: original?.id ?? null
		};
		return { group, date: date(dated), id: Math.min(...storedIds, lead.fromEntryId) };
	});
	groups.sort((a, b) => {
		if (a.date !== b.date) {
			if (a.date === null) return 1;
			if (b.date === null) return -1;
			return a.date < b.date ? -1 : 1;
		}
		return a.id - b.id;
	});
	return groups.map((g) => g.group);
}

/**
 * The unit-level line of a pair: "Transfer between A and B" and how the pair was made, the pair
 * key's words ("paired with B", "matched automatically", "set by you"). Null for one group.
 */
export function pairLine(
	groups: readonly PanelGroup[],
	entries: readonly Entry[],
	args: { accountName: (id: number) => string | undefined; rules: RuleNames; locale: string }
): { text: string; evidence: Evidence | null } | null {
	if (groups.length < 2) return null;
	const [a, b] = groups;
	const name = (id: number) => args.accountName(id) ?? `Account ${id}`;
	const key =
		entries.map((e) => keyOf(e.derivation, 'counterpart')).find((k) => k !== null) ?? null;
	return {
		text: `Transfer between ${name(a.header.accountId)} and ${name(b.header.accountId)}`,
		evidence: describeKey(key, args.rules, args.locale, {
			field: 'counterpart',
			partnerAccount: args.accountName(b.header.accountId)
		})
	};
}
