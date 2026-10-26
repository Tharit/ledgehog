// The panel's blocks grouped by the source transaction they came from (patterns §4.1): a unit
// that spans more than one source (a pair) shows one group per source, each with a header, its
// source strip, its residual block, its splits in the order they were added, and its own "Split
// entry". Pure: it orders and gathers what the views already say. A group is data, so a later
// group that has no entry yet (a counter-leg offer, "created when you commit") can be appended.
import { sourceGroups, type SourceGroup } from './describe.js';
import type { Entry, Money } from '#lib/types/domain.js';
import type { EntryView } from './view.js';

export type GroupHeader = {
	accountId: number;
	/** the booked date of the group's entry; null when it has none yet */
	bookedOn: string | null;
	/** what the source transaction said */
	amount: Money | null;
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
	/**
	 * The group is the counter-leg a commit creates (patterns §4.5): one read-only block, no
	 * editing, no split. `forAccountId` is the account of the leg it is created for.
	 */
	ghost: {
		forAccountId: number | null;
		purpose: string | null;
		/** the ghost is a booking on a clearance account, made by settling from the charge (§5.8) */
		booking: boolean;
	} | null;
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
	for (const view of views.filter((v) => !v.counterLeg)) {
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
					(original ?? lead).amount
			},
			strip,
			views: ordered,
			// a booking's split is its document's: there is nothing to split
			splitEntryId: original && original.booking === null ? original.id : null,
			ghost: null
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
	return [...groups.map((g) => g.group), ...ghostGroups(views)];
}

/** The counter-legs a commit creates, each a group of its own after the real ones. */
function ghostGroups(views: readonly EntryView[]): PanelGroup[] {
	return views
		.filter((v) => v.counterLeg)
		.map((view) => {
			const leg = views.find((v) => v.id === (view.row?.counter_leg_for ?? view.row?.booking_for));
			return {
				key: `counter-leg-${view.id}`,
				sourceId: null,
				header: {
					accountId: view.accountId,
					bookedOn: view.row?.booked_on ?? null,
					amount: view.amount
				},
				strip: null,
				views: [view],
				splitEntryId: null,
				ghost: {
					forAccountId: leg?.accountId ?? null,
					purpose: view.description,
					booking: view.bookingFor !== null
				}
			};
		});
}

export type PartnerDirection = 'above' | 'below';

/**
 * Where each transfer leg's partner sits relative to the leg: its group above or below. Keyed by
 * the leg's entry id; a leg whose partner is not in another group of the panel has no entry.
 */
export function partnerDirections(groups: readonly PanelGroup[]): Map<number, PartnerDirection> {
	const out = new Map<number, PartnerDirection>();
	groups.forEach((group, at) => {
		for (const view of group.views) {
			const partnerId = view.transfer?.partner?.entry_id;
			if (partnerId === undefined || partnerId === null) continue;
			const there = groups.findIndex((g) => g.views.some((v) => v.id === partnerId));
			if (there === -1 || there === at) continue;
			out.set(view.id, there < at ? 'above' : 'below');
		}
	});
	return out;
}
