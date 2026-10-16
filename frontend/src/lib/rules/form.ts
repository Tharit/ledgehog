// The rule editor's form as plain data, and its mapping to and from the API's rule. No matching
// happens here (architecture §6.3): conditions are text the server will judge.
import type { Rule, RuleFields, RuleSets } from '#lib/api/rules.js';
import {
	newConditionRow,
	keepRowsFor,
	rowsFromConditions,
	toConditions,
	type ConditionRow
} from './conditions.js';

export const SETS: readonly RuleSets[] = ['counter_account', 'payee', 'category'];

/** The words for what a rule sets: its list heading, a name for one, and what it does. */
export const SETS_INFO: Record<RuleSets, { group: string; name: string; hint: string }> = {
	counter_account: {
		group: 'Counter-account rules',
		name: 'Counter-account',
		hint: 'Makes the entry a transfer to this account.'
	},
	payee: {
		group: 'Payee rules',
		name: 'Payee',
		hint: 'Sets the entry’s payee.'
	},
	category: {
		group: 'Category rules',
		name: 'Category',
		hint: 'Sets the entry’s category.'
	}
};

export const DEFAULT_PRIORITY = 100;

export type RuleForm = {
	name: string;
	sets: RuleSets;
	/** the id of the counter-account, payee or category `sets` names */
	target: number | null;
	/** every one must hold; a row without a value is not sent */
	conditions: ConditionRow[];
	/** as typed; blank on a new rule leaves it to the server, which places it (spec §5.9) */
	priority: string;
};

export function emptyForm(sets: RuleSets = 'category'): RuleForm {
	return {
		name: '',
		sets,
		target: null,
		conditions: [newConditionRow()],
		priority: ''
	};
}

const TARGET_FIELD = {
	counter_account: 'counter_account_id',
	payee: 'payee_id',
	category: 'category_id'
} as const;

/** The id of what a rule sets: its counter-account, payee or category. */
export function targetId(rule: Rule): number | null {
	return rule[TARGET_FIELD[rule.sets as RuleSets]];
}

export function formFromRule(rule: Rule): RuleForm {
	const sets = rule.sets as RuleSets;
	return {
		name: rule.name,
		sets,
		target: targetId(rule),
		conditions: rowsFromConditions(rule.conditions),
		priority: rule.priority === DEFAULT_PRIORITY ? '' : String(rule.priority)
	};
}

/** The priority as a number: blank is the default, anything but a whole number is null. */
export function parsePriority(text: string): number | null {
	const trimmed = text.trim();
	if (trimmed === '') return DEFAULT_PRIORITY;
	if (!/^-?\d+$/.test(trimmed)) return null;
	const value = Number(trimmed);
	return Number.isSafeInteger(value) && Math.abs(value) < 2 ** 31 ? value : null;
}

/** The `priority` part of a request: the typed number, or nothing for a new rule's blank. */
function priorityField(text: string, editing: boolean): { priority?: number } {
	if (text.trim() === '') return editing ? { priority: DEFAULT_PRIORITY } : {};
	const typed = parsePriority(text);
	return typed === null ? {} : { priority: typed };
}

/** Whether a payee condition applies (a row in the conditions): category rules only. */
export function takesPayeeCondition(sets: RuleSets): boolean {
	return sets === 'category';
}

/** The conditions the request carries: payee rows only for a category rule. */
function requestConditions(form: RuleForm) {
	return toConditions(keepRowsFor(form.conditions, takesPayeeCondition(form.sets)));
}

export function hasCondition(form: RuleForm): boolean {
	return requestConditions(form).length > 0;
}

/** Enough to ask the server what the rule would do: a target, a condition, a usable priority. */
export function isPreviewable(form: RuleForm): boolean {
	return form.target !== null && hasCondition(form) && parsePriority(form.priority) !== null;
}

/** The name a preview is asked with while the field is blank: the server needs one, we need not. */
export const PREVIEW_NAME = 'Untitled rule';

/**
 * The request body for the form: the one target `sets` names, every condition, the priority. A
 * blank priority is not sent when the rule is new: the server places it (spec §5.9). A rule being
 * edited sends the default instead, so that clearing the field means what it says.
 */
export function toFields(form: RuleForm, { forPreview = false, editing = false } = {}): RuleFields {
	const name = form.name.trim();
	const target = form.target ?? undefined;
	return {
		name: name === '' && forPreview ? PREVIEW_NAME : name,
		sets: form.sets,
		counter_account_id: form.sets === 'counter_account' ? target : null,
		payee_id: form.sets === 'payee' ? target : null,
		category_id: form.sets === 'category' ? target : null,
		conditions: requestConditions(form),
		...priorityField(form.priority, editing)
	};
}

/** What the server would see for this form: equal keys, equal requests. */
export function formKey(form: RuleForm): string {
	return JSON.stringify(toFields(form));
}

/** Has the form changed from where it started (`initialKey` is that form's key)? */
export function isDirty(form: RuleForm, initialKey: string): boolean {
	return formKey(form) !== initialKey;
}

/** Is a preview (taken for `previewedKey`) a preview of this form as it stands now? */
export function previewMatchesForm(previewedKey: string | null, form: RuleForm): boolean {
	return previewedKey !== null && previewedKey === formKey(form);
}

export type SaveState = {
	/** a preview of exactly this form has arrived */
	previewCurrent: boolean;
	previewFailed: boolean;
	saving: boolean;
	/** editing a rule, and the form is as stored */
	unchanged: boolean;
};

/** Why "Save rule" cannot be pressed, in words for its tooltip; null when it can. */
export function saveBlock(form: RuleForm, state: SaveState): string | null {
	if (state.saving) return 'Saving…';
	if (form.name.trim() === '') return 'Give the rule a name';
	if (form.target === null) return `Choose the ${SETS_INFO[form.sets].name.toLowerCase()} it sets`;
	if (!hasCondition(form)) return 'Add at least one condition';
	if (parsePriority(form.priority) === null) return 'The priority must be a whole number';
	if (state.unchanged) return 'Nothing has changed';
	if (state.previewFailed) return 'The preview failed; see the message beside it';
	if (!state.previewCurrent) return 'Waiting for the preview of this version of the rule';
	return null;
}
