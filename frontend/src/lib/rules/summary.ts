// A one-line description of a rule's conditions, built from its fields. Display only: it says what
// the rule asks for, never whether an entry meets it (architecture §6.3).

export type ConditionFields = {
	counterparty_ref?: string | null;
	mandate_ref?: string | null;
	name_exact?: string | null;
	name_prefix?: string | null;
	purpose_regex?: string | null;
	booking_text?: string | null;
	condition_payee_id?: number | null;
};

/** The conditions that are set, each as a short phrase, in the editor's order. */
export function conditionParts(
	fields: ConditionFields,
	payeeName: (id: number) => string | undefined = () => undefined
): string[] {
	const parts: string[] = [];
	const text = (value: string | null | undefined) => (value ?? '').trim();
	if (text(fields.counterparty_ref)) parts.push(`reference ${text(fields.counterparty_ref)}`);
	if (text(fields.mandate_ref)) parts.push(`mandate ${text(fields.mandate_ref)}`);
	if (text(fields.name_prefix)) parts.push(`name starts with “${text(fields.name_prefix)}”`);
	if (text(fields.name_exact)) parts.push(`name is “${text(fields.name_exact)}”`);
	if (text(fields.purpose_regex)) parts.push(`purpose matches /${text(fields.purpose_regex)}/`);
	if (text(fields.booking_text)) parts.push(`booking text “${text(fields.booking_text)}”`);
	const payee = fields.condition_payee_id;
	if (payee !== null && payee !== undefined) {
		parts.push(`payee is ${payeeName(payee) ?? `payee ${payee}`}`);
	}
	return parts;
}

/** "name starts with “PAYPAL *” and purpose matches /cloud/": all of them must hold. */
export function summarizeConditions(
	fields: ConditionFields,
	payeeName?: (id: number) => string | undefined
): string {
	const parts = conditionParts(fields, payeeName);
	return parts.length === 0 ? 'No conditions' : parts.join(' and ');
}
