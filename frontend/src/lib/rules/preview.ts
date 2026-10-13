// What the preview table shows besides what the server sent: which source columns there are, and
// a derivation key in the one vocabulary of patterns §4.3. Nothing here matches anything.
import type { RulePreviewRow } from '#lib/api/rules.js';
import { CONDITION_FIELDS, type Condition, type ConditionField, fieldsRead } from './conditions.js';

/**
 * The source columns of a preview: the counterparty name always, then every other field the
 * conditions read, in the editor's order.
 */
export function sourceColumns(conditions: readonly Condition[]): ConditionField[] {
	const read = new Set<ConditionField>(fieldsRead(conditions));
	read.add('counterparty_name');
	return CONDITION_FIELDS.filter((field) => read.has(field));
}

/** A row's text in one source field; null when it has no source or the field is empty. */
export function sourceText(
	row: Pick<RulePreviewRow, 'source'>,
	field: ConditionField
): string | null {
	const text = row.source?.[field];
	return text === undefined || text === null || text === '' ? null : text;
}

/**
 * The basis of a value as a short phrase, or null when there is no key. `ruleName` gives a rule's
 * name; a rule it does not know is "rule deleted" (patterns §4.3).
 */
export function keyLabel(
	key: RulePreviewRow['current_key'],
	ruleName: (id: number) => string | undefined
): string | null {
	if (!key) return null;
	switch (key.pass) {
		case 'rule': {
			const basis = key.basis as { rule_id?: unknown } | null | undefined;
			const id = typeof basis?.rule_id === 'number' ? basis.rule_id : null;
			const name = id === null ? undefined : ruleName(id);
			return name === undefined ? 'rule deleted' : `rule: ${name}`;
		}
		case 'history':
			return 'history';
		case 'user':
			return 'you';
		case 'own_account':
			return 'own account';
		case 'llm':
			return 'model';
		case 'matcher_decision':
			return 'matched automatically';
		case 'matcher_proposal':
			return 'document matched';
		default:
			return typeof key.pass === 'string' ? key.pass : null;
	}
}
