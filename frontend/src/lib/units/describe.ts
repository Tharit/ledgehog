// The unit as words: its shape, its title, its state in plain language, where its sources are.
// Pure and DOM-free so the panel and the queue say the same things. Nothing here decides
// anything about a unit: state and entries are the server's.
import type { Lookups } from '#lib/ledger/lookups.js';
import type { Entry, SourceTransaction } from '#lib/types/domain.js';
import type { Unit, UnitReason, UnitState } from './types.js';

/** Shown when a derived entry (opening, valuation, reconciliation) is opened: it has no review. */
export const DERIVED_NOTICE = 'Derived from a balance record — correct the record.';

/** What the panel says when the unit does not exist: derived entries, or one that went away. */
export const NO_REVIEW_TITLE = 'This entry has no review';
export const NO_REVIEW_TEXT =
	'It is derived from a balance record, so there is nothing to review: correct the record instead. Or it no longer exists.';

export const REASON_TEXT: Readonly<Record<UnitReason, string>> = {
	incomplete: 'Incomplete',
	unpaired_transfer: 'Waiting for its partner',
	non_standing_keys: 'Proposals to check'
};

/** The state of a unit in plain words: "Confirmed", or the reasons it is not. */
export function stateText(state: UnitState): string {
	if (state.confirmed) return 'Confirmed';
	const reasons = state.reasons.map((reason) => REASON_TEXT[reason] ?? reason);
	return reasons.length > 0 ? reasons.join(' · ') : 'In review';
}

export type UnitShape = 'single' | 'split' | 'pair';

/** A pair has two entries that name each other; any other unit of several entries is a split. */
export function unitShape(
	entries: readonly Pick<Entry, 'id' | 'counterpart_entry_id'>[]
): UnitShape {
	if (entries.length < 2) return 'single';
	const ids = new Set(entries.map((e) => e.id));
	const paired = entries.some(
		(e) => e.counterpart_entry_id !== null && ids.has(e.counterpart_entry_id)
	);
	return paired ? 'pair' : 'split';
}

/** The entry that names the unit: its anchor, else the lowest id. */
export function anchorEntry(unit: Pick<Unit, 'anchor_entry_id' | 'entries'>): Entry | undefined {
	return unit.entries.find((e) => e.id === unit.anchor_entry_id) ?? unit.entries[0];
}

/** What an entry is called in a list: its text, else its counterparty, else "Entered by hand". */
export function entryLabel(entry: Entry): string {
	return (
		entry.display_text?.trim() ||
		entry.source?.counterparty_name?.trim() ||
		(entry.authored ? 'Entered by hand' : `Entry ${entry.id}`)
	);
}

/** The panel's title: the text of the anchor; a pair names its accounts; a split says how many. */
export function unitTitle(
	unit: Pick<Unit, 'anchor_entry_id' | 'entries'>,
	lookups: Lookups
): string {
	const anchor = anchorEntry(unit);
	if (!anchor) return 'Unit';
	const shape = unitShape(unit.entries);
	if (shape === 'pair') {
		const out = unit.entries.find((e) => e.amount.amount < 0) ?? anchor;
		const into = unit.entries.find((e) => e.id !== out.id) ?? anchor;
		const name = (e: Entry) =>
			lookups.accounts.get(e.account_id)?.name ?? `Account ${e.account_id}`;
		return `Transfer ${name(out)} → ${name(into)}`;
	}
	if (shape === 'split') return `${entryLabel(anchor)} (split in ${unit.entries.length})`;
	return entryLabel(anchor);
}

export type SourceGroup =
	| { kind: 'source'; key: number; source: SourceTransaction; entryIds: number[] }
	| { kind: 'authored'; entryIds: number[] };

/**
 * Where the entries came from: one group per distinct source transaction (the entries of a split
 * share one), and one for the entries entered by hand. Entries with neither (derived ones, a
 * counter-leg the data does not describe) are not listed.
 */
export function sourceGroups(entries: readonly Entry[]): SourceGroup[] {
	const groups: SourceGroup[] = [];
	const bySource = new Map<number, Extract<SourceGroup, { kind: 'source' }>>();
	let authored: Extract<SourceGroup, { kind: 'authored' }> | null = null;
	for (const entry of entries) {
		if (entry.source && entry.source_transaction_id !== null) {
			let group = bySource.get(entry.source_transaction_id);
			if (!group) {
				group = {
					kind: 'source',
					key: entry.source_transaction_id,
					source: entry.source,
					entryIds: []
				};
				bySource.set(entry.source_transaction_id, group);
				groups.push(group);
			}
			group.entryIds.push(entry.id);
		} else if (entry.authored) {
			if (!authored) {
				authored = { kind: 'authored', entryIds: [] };
				groups.push(authored);
			}
			authored.entryIds.push(entry.id);
		}
	}
	return groups;
}

/** What a failed load of `what` ("The unit", "The review queue") says, routed by code (patterns §8). */
export function describeUnitLoadError(
	code: string,
	what: string
): { title: string; message: string; retryable: boolean } {
	switch (code) {
		case 'network_error':
			return {
				title: `${what} could not be loaded`,
				message: 'The server could not be reached. Check the connection and try again.',
				retryable: true
			};
		case 'unauthenticated':
			return {
				title: 'You are signed out',
				message: `Your session has ended. Sign in again to see ${what.toLowerCase()}.`,
				retryable: false
			};
		default:
			return {
				title: `${what} could not be loaded`,
				message: 'The server could not answer this request. Try again in a moment.',
				retryable: true
			};
	}
}
