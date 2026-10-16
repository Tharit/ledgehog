// A rule's conditions as the editor holds and the request carries them: a list of
// `{field, op, value}`, all of which must hold (spec §5.9). Nothing here judges whether an entry
// meets one: the server does, in the preview (architecture §6.3).

/** The fields of the entry's source transaction a condition can read, in the editor's order. */
export const SOURCE_FIELDS = [
	'counterparty_name',
	'counterparty_ref',
	'purpose',
	'booking_text',
	'mandate_ref'
] as const;
export type SourceField = (typeof SOURCE_FIELDS)[number];

/** The text fields of the entry itself (not of its source) a condition can read: its document's. */
export const ENTRY_FIELDS = ['document_merchant', 'document_line'] as const;
export type EntryField = (typeof ENTRY_FIELDS)[number];

/** The fields a condition can read, in the order the editor shows them: source, then entry. */
export const CONDITION_FIELDS = [...SOURCE_FIELDS, ...ENTRY_FIELDS] as const;
export type ConditionField = (typeof CONDITION_FIELDS)[number];

/** The two groups of the field picker and of the example's table. */
export const SOURCE_GROUP = 'From the source transaction';
export const ENTRY_GROUP = 'From the entry';

export function isSourceField(field: ConditionField): field is SourceField {
	return (SOURCE_FIELDS as readonly string[]).includes(field);
}

export const CONDITION_OPS = ['equals', 'starts_with', 'contains', 'regex'] as const;
export type ConditionOp = (typeof CONDITION_OPS)[number];

/** The plain words for a field, in the editor, the preview's headers and the summaries. */
export const FIELD_LABELS: Record<ConditionField, string> = {
	counterparty_name: 'Counterparty name',
	counterparty_ref: 'Counterparty IBAN or reference',
	purpose: 'Purpose',
	booking_text: 'Booking text',
	mandate_ref: 'Mandate reference',
	document_merchant: 'Document merchant name',
	document_line: 'Document line'
};

/** The payee condition's field and its one operator: the value is a payee id as a digit string. */
export const PAYEE_FIELD = 'payee';
export const PAYEE_OP = 'is';
export const OP_LABELS_PAYEE = 'is';

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

/** A row's field: one of the text fields, or the payee (category rules only). */
export type RowField = ConditionField | typeof PAYEE_FIELD;
/** A row's operator: one of the four, or `is` (the payee's only one). */
export type RowOp = ConditionOp | typeof PAYEE_OP;

/** One row of the editor; `key` identifies the row while it is edited, never leaves the client. */
export type ConditionRow = { key: number; field: RowField; op: RowOp; value: string };

export function isPayeeRow(row: Pick<ConditionRow, 'field'>): boolean {
	return row.field === PAYEE_FIELD;
}

/** The payee a row names, or null while none is picked (or the value is no id). */
export function payeeOfRow(row: Pick<ConditionRow, 'value'>): number | null {
	const text = row.value.trim();
	return /^\d+$/.test(text) ? Number(text) : null;
}

/** The rows a rule that sets `sets` can hold: payee rows only belong to category rules. */
export function keepRowsFor(rows: readonly ConditionRow[], takesPayee: boolean): ConditionRow[] {
	const kept = takesPayee ? [...rows] : rows.filter((row) => !isPayeeRow(row));
	return kept.length > 0 ? kept : [newConditionRow()];
}

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
	const rows = conditions.flatMap((c) => {
		if (c.field === PAYEE_FIELD && c.op === PAYEE_OP) {
			return [newConditionRow({ field: PAYEE_FIELD, op: PAYEE_OP, value: c.value })];
		}
		return isConditionField(c.field) && isConditionOp(c.op)
			? [newConditionRow({ field: c.field, op: c.op, value: c.value })]
			: [];
	});
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
	if (field === PAYEE_FIELD) return 'Payee';
	return isConditionField(field) ? FIELD_LABELS[field] : field;
}

/**
 * One condition in words: `Counterparty name starts with "REWE"`, `Payee is REWE`. A payee the
 * lookup does not know reads `Payee is deleted`.
 */
export function conditionText(
	condition: Condition,
	payeeName: (id: number) => string | undefined = () => undefined
): string {
	if (condition.field === PAYEE_FIELD) {
		const id = payeeOfRow(condition);
		const name = id === null ? undefined : payeeName(id);
		return `Payee is ${name ?? 'deleted'}`;
	}
	const op = isConditionOp(condition.op) ? OP_WORDS[condition.op] : condition.op;
	return `${fieldLabel(condition.field)} ${op} "${condition.value}"`;
}
