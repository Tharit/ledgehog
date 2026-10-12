// Starting a rule from an entry: its text fields become SUGGESTIONS the user ticks. This is text
// prefill only. Nothing here asks whether a rule would match an entry: the server judges that, in
// the preview (spec §5.9, architecture §6.3).
import type { Entry } from '#lib/types/domain.js';
import { emptyForm, type ConditionField, type RuleForm } from './form.js';

/**
 * What an entry offers a rule. The source fields (`counterparty_ref`, `mandate_ref`,
 * `booking_text`) are not in the entries list yet; when the API carries them they are used as is.
 */
export type EntryFacts = Pick<Entry, 'id' | 'counterparty_name' | 'category_id'> &
	Partial<{
		counterparty_ref: string | null;
		mandate_ref: string | null;
		booking_text: string | null;
	}>;

export type Suggestion = { field: ConditionField; value: string };

function clean(value: string | null | undefined): string {
	return (value ?? '').trim();
}

/** The candidate conditions an entry offers, in the editor's order; none is applied. */
export function suggestionsFromEntry(entry: EntryFacts): Suggestion[] {
	const name = clean(entry.counterparty_name);
	const candidates: [ConditionField, string][] = [
		['counterparty_ref', clean(entry.counterparty_ref)],
		['mandate_ref', clean(entry.mandate_ref)],
		['name_prefix', name],
		['name_exact', name],
		['booking_text', clean(entry.booking_text)]
	];
	return candidates.flatMap(([field, value]) => (value === '' ? [] : [{ field, value }]));
}

/**
 * The form to start from: no condition set (the suggestions wait to be ticked), and the entry's
 * own category as the target to start from, which the user may change.
 */
export function formFromEntry(entry: EntryFacts): RuleForm {
	return { ...emptyForm('category'), target: entry.category_id };
}

/** Is this suggestion in the form right now? (A ticked box is the field holding its value.) */
export function isApplied(form: RuleForm, suggestion: Suggestion): boolean {
	return form[suggestion.field].trim() === suggestion.value;
}

/** Tick or untick a suggestion: the field takes the value, or is emptied again. */
export function applySuggestion(form: RuleForm, suggestion: Suggestion, on: boolean): RuleForm {
	return { ...form, [suggestion.field]: on ? suggestion.value : '' };
}

/** Where an entry's rule starts: the entry's id, and (so it can be found) its date and account. */
export type FromEntry = { id: number; on?: string; accountId?: number };

export function parseFromParams(search: string): FromEntry | null {
	const params = new URLSearchParams(search);
	const id = Number(params.get('from'));
	if (!Number.isSafeInteger(id) || id <= 0) return null;
	const on = params.get('on') ?? undefined;
	const account = Number(params.get('account'));
	return {
		id,
		on: on && /^\d{4}-\d{2}-\d{2}$/.test(on) ? on : undefined,
		accountId: Number.isSafeInteger(account) && account > 0 ? account : undefined
	};
}

/** `/settings/rules/new?from=<id>` (architecture §6.2), with the hints that find the entry. */
export function newRuleUrl(entry: Pick<Entry, 'id' | 'booked_on' | 'account_id'>): string {
	const params = new URLSearchParams({
		from: String(entry.id),
		on: entry.booked_on,
		account: String(entry.account_id)
	});
	return `/settings/rules/new?${params.toString()}`;
}
