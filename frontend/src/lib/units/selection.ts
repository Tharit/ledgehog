// Committing units as seen (views/review-queue.md): which units a row may be ticked for, and what
// "the values its row showed" are compared against. Pure: it reads what the rows and the preview say.
import type { Entry } from '#lib/types/domain.js';
import { FIELD_NAMES, type FieldName, type FieldValue } from './draft.js';
import { STORED_VALUE } from './view.js';
import type { Unit, UnitPreview } from './types.js';

export const MODEL_LOOKING = 'The model is still looking';
export const NOT_CLASSIFIED = 'No category yet';
export const NOT_PAIRED = 'Transfer not paired';
export const ALREADY_COMMITTED = 'Already committed';

/**
 * Why a commit would not confirm what the row shows, or null where it would: a complete
 * interpretation (a flow with its category, a transfer with its pair) and no answer of the model
 * still to come. `committed`: the unit was committed already (its rows are marked resolved).
 *
 * Judged from the entries alone (their flags and pairing), never from `unit.state`: a patch
 * (patterns §7) rewrites a unit's entries but not its state, and eligibility must follow the rows
 * as they are shown. A category a proposal fills is a value on the entry (`unclassified` is "no
 * category", not "no decided category"), so it counts: a commit would confirm what the row shows.
 */
export function selectionReason(unit: Unit, committed = false): string | null {
	if (committed) return ALREADY_COMMITTED;
	if (unit.entries.some((e) => e.model_pending)) return MODEL_LOOKING;
	const flags = unit.entries.flatMap((e) => e.review_flags);
	if (flags.includes('unclassified') || unit.entries.some((e) => e.type === null)) {
		return NOT_CLASSIFIED;
	}
	if (
		flags.includes('unmatched_transfer') ||
		flags.includes('waiting') ||
		unit.entries.some((e) => e.type === 'transfer' && e.counterpart_entry_id === null)
	)
		return NOT_PAIRED;
	return null;
}

const FIELD_WORD: Readonly<Record<FieldName | 'description', string>> = {
	type: 'type',
	category: 'category',
	counter_account: 'counter account',
	payee: 'payee',
	description: 'description'
};

export type Changed = { field: FieldName | 'description'; value: FieldValue };

const text = (value: string | null | undefined) => (value ?? '').trim();

/**
 * The first value (type, category, counter-account, payee, description) of the unit as seen that
 * the fresh preview ends in differently, or null. The entries' own values are compared, never the
 * bases: "2 of 2" where the row said "1 of 1" is not a change.
 */
export function changedSince(
	seen: readonly Entry[],
	preview: Pick<UnitPreview, 'rows'>
): Changed | null {
	for (const entry of seen) {
		const row = preview.rows.find((r) => r.id === entry.id);
		if (!row) continue;
		for (const field of FIELD_NAMES) {
			const out = row.fields[field];
			if (out && out.value !== STORED_VALUE[field](entry)) return { field, value: out.value };
		}
		if (text(row.description) !== text(entry.description))
			return { field: 'description', value: row.description };
	}
	return null;
}

/** "Changed since you saw it: category is now Groceries". `name` words a value (a category's name). */
export function changedText(
	change: Changed,
	name: (field: Changed['field'], value: FieldValue) => string
): string {
	return `Changed since you saw it: ${FIELD_WORD[change.field]} is now ${name(change.field, change.value)}`;
}
