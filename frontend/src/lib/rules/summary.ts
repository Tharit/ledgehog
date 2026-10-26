// A one-line description of a rule's conditions, in plain language. Display only: it says what
// the rule asks for, never whether an entry meets it (architecture §6.3).
import { conditionText, type Condition } from './conditions.js';

export type ConditionFields = {
	conditions?: readonly Condition[];
};

/** The conditions, each as a short phrase. */
export function conditionParts(
	fields: ConditionFields,
	payeeName: (id: number) => string | undefined = () => undefined,
	accountName: (id: number) => string | undefined = () => undefined
): string[] {
	return (fields.conditions ?? []).map((c) => conditionText(c, payeeName, accountName));
}

/** `Counterparty name starts with "REWE" and Purpose contains "Markt"`: all of them must hold. */
export function summarizeConditions(
	fields: ConditionFields,
	payeeName?: (id: number) => string | undefined,
	accountName?: (id: number) => string | undefined
): string {
	const parts = conditionParts(fields, payeeName, accountName);
	return parts.length === 0 ? 'No conditions' : parts.join(' and ');
}
