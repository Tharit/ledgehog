// What the rule screens say, routed by the kind of failure (patterns §8), never by a message.
import type { RuleError } from '#lib/api/rules.js';
import { formatCount } from '#lib/format/index.js';
import { SETTLE_STALE } from '#lib/ledger/errors.js';
import { RULES_PATH } from './links.js';

/** The form fields a failure can point at; the others are shown as one line. */
export type FieldKey =
	| 'name'
	| 'target'
	| 'condition_payee_id'
	| 'counterparty_ref'
	| 'mandate_ref'
	| 'name_prefix'
	| 'name_exact'
	| 'purpose_regex'
	| 'booking_text'
	| 'priority';

const FIELD_OF: Record<string, FieldKey> = {
	name: 'name',
	counter_account_id: 'target',
	payee_id: 'target',
	category_id: 'target',
	condition_payee_id: 'condition_payee_id',
	counterparty_ref: 'counterparty_ref',
	mandate_ref: 'mandate_ref',
	name_prefix: 'name_prefix',
	name_exact: 'name_exact',
	purpose_regex: 'purpose_regex',
	booking_text: 'booking_text',
	priority: 'priority'
};

export type FieldErrors = Partial<Record<FieldKey, string>>;

/** The part of a failure that belongs to one field, to show beside it. */
export function fieldErrors(error: RuleError | null): FieldErrors {
	if (!error) return {};
	switch (error.kind) {
		case 'duplicate_name':
			return { name: 'A rule with this name already exists.' };
		case 'invalid_rule': {
			const key = FIELD_OF[error.field];
			return key ? { [key]: error.message } : {};
		}
		case 'validation': {
			const found: FieldErrors = {};
			for (const problem of error.problems) {
				const key = FIELD_OF[problem.field];
				if (key && !found[key]) found[key] = problem.message;
			}
			return found;
		}
		case 'stale_reference': {
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
			return error.field in FIELD_OF
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

export type RuleDone =
	| { action: 'saved'; name: string; touched: number; settleFailed: boolean }
	| { action: 'deleted'; name: string; touched: number; settleFailed: boolean };

/** The list address to go to after a write, carrying what settled so the list can say so. */
export function doneUrl(done: RuleDone): string {
	const params = new URLSearchParams({
		[PARAM]: done.action,
		name: done.name,
		touched: String(done.touched)
	});
	if (done.settleFailed) params.set('stale', '1');
	return `${RULES_PATH}?${params.toString()}`;
}

/** The notice for a list address that carries one (see `doneUrl`), or null. */
export function doneFromSearch(search: string): RuleDone | null {
	const params = new URLSearchParams(search);
	const action = params.get(PARAM);
	const name = params.get('name');
	if ((action !== 'saved' && action !== 'deleted') || name === null) return null;
	const touched = Number(params.get('touched'));
	return {
		action,
		name,
		touched: Number.isSafeInteger(touched) && touched > 0 ? touched : 0,
		settleFailed: params.get('stale') === '1'
	};
}

/** "Rule “Rent” saved. Settling touched 3 entries." */
export function doneText(done: RuleDone, locale = 'en'): string {
	const verb = done.action === 'saved' ? 'saved' : 'deleted';
	const touched =
		done.touched === 0
			? 'No entries needed settling.'
			: `Settling touched ${formatCount(done.touched, locale)} ${done.touched === 1 ? 'entry' : 'entries'}.`;
	return `Rule “${done.name}” ${verb}. ${touched}${done.settleFailed ? ` ${SETTLE_STALE}` : ''}`;
}
