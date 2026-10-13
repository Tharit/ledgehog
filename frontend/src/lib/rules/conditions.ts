// A rule's conditions as the editor holds and the request carries them: a list of
// `{field, op, value}`, all of which must hold (spec §5.9). Nothing here judges whether an entry
// meets one: the server does, in the preview (architecture §6.3).

/** The fields a condition can read, in the order the editor and the preview show them. */
export const CONDITION_FIELDS = [
	'counterparty_name',
	'counterparty_ref',
	'purpose',
	'booking_text',
	'mandate_ref'
] as const;
export type ConditionField = (typeof CONDITION_FIELDS)[number];

export const CONDITION_OPS = ['equals', 'starts_with', 'contains', 'regex'] as const;
export type ConditionOp = (typeof CONDITION_OPS)[number];

/** The plain words for a field, in the editor, the preview's headers and the summaries. */
export const FIELD_LABELS: Record<ConditionField, string> = {
	counterparty_name: 'Counterparty name',
	counterparty_ref: 'Counterparty IBAN or reference',
	purpose: 'Purpose',
	booking_text: 'Booking text',
	mandate_ref: 'Mandate reference'
};

/** The words for an operator in the editor's menu. */
export const OP_LABELS: Record<ConditionOp, string> = {
	equals: 'is',
	starts_with: 'starts with',
	contains: 'contains',
	regex: 'matches pattern (regex)'
};

/** The same, in a sentence: "Purpose matches pattern “cloud|hosting”". */
const OP_WORDS: Record<ConditionOp, string> = {
	equals: 'is',
	starts_with: 'starts with',
	contains: 'contains',
	regex: 'matches pattern'
};

/** What the server says of a condition. Field and operator are open strings on the wire. */
export type Condition = { field: string; op: string; value: string };

/** One row of the editor; `key` identifies the row while it is edited, never leaves the client. */
export type ConditionRow = { key: number; field: ConditionField; op: ConditionOp; value: string };

let nextKey = 1;

/** A new row: counterparty name, contains, nothing typed yet. */
export function newConditionRow(over: Partial<Omit<ConditionRow, 'key'>> = {}): ConditionRow {
	return { key: nextKey++, field: 'counterparty_name', op: 'contains', value: '', ...over };
}

export function isConditionField(field: string): field is ConditionField {
	return (CONDITION_FIELDS as readonly string[]).includes(field);
}

export function isConditionOp(op: string): op is ConditionOp {
	return (CONDITION_OPS as readonly string[]).includes(op);
}

/** The rows for stored conditions, or the one blank row an editor starts with. */
export function rowsFromConditions(conditions: readonly Condition[]): ConditionRow[] {
	const rows = conditions.flatMap((c) =>
		isConditionField(c.field) && isConditionOp(c.op)
			? [newConditionRow({ field: c.field, op: c.op, value: c.value })]
			: []
	);
	return rows.length > 0 ? rows : [newConditionRow()];
}

/** The positions of the rows a request carries: a row without a value is left out. */
export function requestRows(rows: readonly ConditionRow[]): number[] {
	return rows.flatMap((row, i) => (row.value.trim() === '' ? [] : [i]));
}

/** The conditions as the request carries them: trimmed, blank rows left out, order kept. */
export function toConditions(rows: readonly ConditionRow[]): Condition[] {
	return requestRows(rows).map((i) => ({
		field: rows[i].field,
		op: rows[i].op,
		value: rows[i].value.trim()
	}));
}

/** The fields the conditions read, once each, in the editor's order. */
export function fieldsRead(conditions: readonly Condition[]): ConditionField[] {
	return CONDITION_FIELDS.filter((field) => conditions.some((c) => c.field === field));
}

export function fieldLabel(field: string): string {
	return isConditionField(field) ? FIELD_LABELS[field] : field;
}

/** One condition in words: `Counterparty name starts with "REWE"`. */
export function conditionText(condition: Condition): string {
	const op = isConditionOp(condition.op) ? OP_WORDS[condition.op] : condition.op;
	return `${fieldLabel(condition.field)} ${op} "${condition.value}"`;
}
