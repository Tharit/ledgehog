// What the preview table shows besides what the server sent: which source columns there are
// (the words for a derivation key are units/evidence.ts). Nothing here matches anything.
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
