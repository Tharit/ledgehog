// What the rule screens say, routed by the kind of failure (patterns §8), never by a message.
import type { RuleError, RuleWriteOut } from '#lib/api/rules.js';
import { formatCount } from '#lib/format/index.js';
import { SETTLE_STALE } from '#lib/ledger/errors.js';
import { RULES_PATH } from './links.js';

/** The form fields a failure can point at; the others are shown as one line. */
export type FieldKey = 'name' | 'target' | 'conditions' | 'priority';

const FIELD_OF: Record<string, FieldKey> = {
	name: 'name',
	counter_account_id: 'target',
	payee_id: 'target',
	category_id: 'target',
	conditions: 'conditions',
	priority: 'priority'
};

/** `conditions[2]` or `conditions[2].value`: which row of the request, and which part of it. */
const CONDITION_PART = /^conditions\[(\d+)\](?:\.(field|op|value))?$/;

/** What a row says when the server finds its payee gone at write time. */
export const PAYEE_GONE = 'This payee no longer exists.';

/**
 * What to show beside the form's fields: by field, and for the condition rows by position in the
 * editor (`rows`), which is not the position in the request when blank rows were left out.
 */
export type FieldErrors = Partial<Record<FieldKey, string>> & { rows?: Record<number, string> };

/** A failure's place is one the form shows beside a field or a row. */
function isFieldLevel(field: string): boolean {
	return field in FIELD_OF || CONDITION_PART.test(field);
}

/** The server's message about a row names the request's position ("conditions[2]: ..."): drop it. */
function rowMessage(message: string): string {
	const text = message.replace(/^conditions\[\d+\]:\s*/, '');
	return text.charAt(0).toUpperCase() + text.slice(1);
}

function place(found: FieldErrors, field: string, message: string, rowOf: readonly number[]): void {
	const part = CONDITION_PART.exec(field);
	if (part) {
		const at = Number(part[1]);
		const row = rowOf[at] ?? at;
		found.rows = { ...found.rows, [row]: found.rows?.[row] ?? rowMessage(message) };
		return;
	}
	const key = FIELD_OF[field];
	if (key && !found[key]) found[key] = message;
}

/**
 * The part of a failure that belongs to one field or one condition row, to show beside it.
 * `rowOf` maps a position in the request's conditions to the editor's row (see `requestRows`).
 */
export function fieldErrors(error: RuleError | null, rowOf: readonly number[] = []): FieldErrors {
	if (!error) return {};
	const found: FieldErrors = {};
	switch (error.kind) {
		case 'duplicate_name':
			return { name: 'A rule with this name already exists.' };
		case 'invalid_rule':
			place(found, error.field, error.message, rowOf);
			return found;
		case 'validation':
			for (const problem of error.problems) place(found, problem.field, problem.message, rowOf);
			return found;
		case 'stale_reference': {
			const part = error.field ? CONDITION_PART.exec(error.field) : null;
			if (part) {
				const at = Number(part[1]);
				return { rows: { [rowOf[at] ?? at]: PAYEE_GONE } };
			}
			const key = error.field ? FIELD_OF[error.field] : undefined;
			return key ? { [key]: 'This no longer exists. Choose another.' } : {};
		}
		default:
			return {};
	}
}

/** The one-line account of a failure, for the notice line. Field-level detail lives at the field. */
export function describeRuleError(error: RuleError, locale = 'en'): string {
	switch (error.kind) {
		case 'duplicate_name':
			return 'A rule with this name already exists. Choose another name.';
		case 'filter_result_changed':
			return `The result changed (${formatCount(error.expected, locale)} entries before, ${formatCount(error.actual, locale)} now). The preview was refreshed; check it and save again.`;
		case 'stale_reference':
			return `${error.entity ? capitalise(error.entity) : 'A value'} you chose no longer exists (merged or deleted elsewhere). The lists were reloaded; choose again.`;
		case 'invalid_rule':
			return isFieldLevel(error.field)
				? 'The server did not accept this rule; see the highlighted field.'
				: `The server did not accept this rule: ${error.message}`;
		case 'validation':
			return 'The server did not accept this rule; check the highlighted fields.';
		case 'not_found':
			return 'This rule no longer exists. It was deleted elsewhere.';
		case 'unauthenticated':
			return 'Your session has ended. Sign in again.';
		case 'network':
			return 'The server could not be reached. Check the connection and try again.';
		default:
			return 'The server could not do this. Try again in a moment.';
	}
}

function capitalise(text: string): string {
	return text.charAt(0).toUpperCase() + text.slice(1);
}

const PARAM = 'done';

/** Where the entries a write settled stand afterwards (`settle_breakdown` of the write response). */
export type SettleBreakdown = {
	total: number;
	thisRule: number;
	history: number;
	otherRules: number;
	other: number;
};

/** `breakdown` is null when settling failed or told nothing: the notice then only names the write. */
export type RuleDone =
	| { action: 'saved'; name: string; breakdown: SettleBreakdown | null; settleFailed: boolean }
	| { action: 'deleted'; name: string; breakdown: SettleBreakdown | null; settleFailed: boolean };

/** The breakdown of a write response, in the shape the notice takes. */
export function breakdownOf(
	out: Pick<RuleWriteOut, 'settle_breakdown'> | null | undefined
): SettleBreakdown | null {
	const b = out?.settle_breakdown;
	if (!b) return null;
	return {
		total: b.total,
		thisRule: b.this_rule,
		history: b.history,
		otherRules: b.other_rules,
		other: b.other
	};
}

const BREAKDOWN_PARAMS = [
	['total', 'total'],
	['this', 'thisRule'],
	['history', 'history'],
	['rules', 'otherRules'],
	['other', 'other']
] as const;

/** The list address to go to after a write, carrying what settled so the list can say so. */
export function doneUrl(done: RuleDone): string {
	const params = new URLSearchParams({ [PARAM]: done.action, name: done.name });
	if (done.breakdown) {
		for (const [key, field] of BREAKDOWN_PARAMS) params.set(key, String(done.breakdown[field]));
	}
	if (done.settleFailed) params.set('stale', '1');
	return `${RULES_PATH}?${params.toString()}`;
}

function breakdownFrom(params: URLSearchParams): SettleBreakdown | null {
	const values: number[] = [];
	for (const [key] of BREAKDOWN_PARAMS) {
		const raw = params.get(key);
		const n = raw === null || raw === '' ? Number.NaN : Number(raw);
		if (!Number.isSafeInteger(n) || n < 0) return null;
		values.push(n);
	}
	const [total, thisRule, history, otherRules, other] = values;
	return { total, thisRule, history, otherRules, other };
}

/** The notice for a list address that carries one (see `doneUrl`), or null. */
export function doneFromSearch(search: string): RuleDone | null {
	const params = new URLSearchParams(search);
	const action = params.get(PARAM);
	const name = params.get('name');
	if ((action !== 'saved' && action !== 'deleted') || name === null) return null;
	return {
		action,
		name,
		breakdown: breakdownFrom(params),
		settleFailed: params.get('stale') === '1'
	};
}

const NO_CHANGE = 'No entries changed.';

function entries(n: number, locale: string): string {
	return `${formatCount(n, locale)} ${n === 1 ? 'entry' : 'entries'}`;
}

function savedParts(b: SettleBreakdown, locale: string): string[] {
	const parts: string[] = [];
	const rest = b.other + b.otherRules;
	if (b.thisRule > 0) {
		parts.push(`${entries(b.thisRule, locale)} now ${b.thisRule === 1 ? 'follows' : 'follow'} it.`);
	}
	if (b.history > 0) {
		const stay = b.history === 1 ? 'it stays' : 'they stay';
		parts.push(
			b.thisRule > 0
				? `History then proposed it for ${formatCount(b.history, locale)} more; ${stay} in review for you to check.`
				: `History proposed it for ${entries(b.history, locale)}; ${stay} in review for you to check.`
		);
	}
	if (rest > 0) {
		const lead = b.thisRule > 0 || b.history > 0 ? `${formatCount(rest, locale)} other` : '';
		const noun = lead ? (rest === 1 ? 'entry' : 'entries') : entries(rest, locale);
		parts.push(`${lead ? `${lead} ${noun}` : noun} ${rest === 1 ? 'was' : 'were'} updated.`);
	}
	return parts;
}

function deletedParts(b: SettleBreakdown, locale: string): string[] {
	const parts: string[] = [];
	if (b.otherRules > 0) {
		parts.push(
			`${formatCount(b.otherRules, locale)} now ${b.otherRules === 1 ? 'follows' : 'follow'} another rule`
		);
	}
	if (b.history > 0) {
		parts.push(`${formatCount(b.history, locale)} got a proposal from history`);
	}
	if (b.other + b.thisRule > 0) {
		parts.push(`${formatCount(b.other + b.thisRule, locale)} changed otherwise`);
	}
	return [
		`${entries(b.total, locale)} ${b.total === 1 ? 'was' : 'were'} updated: ${parts.join(', ')}.`
	];
}

/**
 * "Rule “Rent” saved. 9 entries now follow it. History then proposed it for 15 more; they stay in
 * review for you to check. 3 other entries were updated." / "Rule “Rent” deleted. 4 entries were
 * updated: 3 now follow another rule, 1 got a proposal from history."
 */
export function doneText(done: RuleDone, locale = 'en'): string {
	const verb = done.action === 'saved' ? 'saved' : 'deleted';
	const b = done.breakdown;
	let detail: string[] = [];
	if (b) {
		if (b.total === 0) detail = [NO_CHANGE];
		else detail = done.action === 'saved' ? savedParts(b, locale) : deletedParts(b, locale);
		if (detail.length === 0) detail = [NO_CHANGE];
	}
	return [
		`Rule “${done.name}” ${verb}.`,
		...detail,
		...(done.settleFailed ? [SETTLE_STALE] : [])
	].join(' ');
}
