import type { Rule, RuleSets } from '#lib/api/rules.js';
import { SETS } from './form.js';

export type RuleGroup = { sets: RuleSets; rules: Rule[] };

/**
 * The rules by what they set, in evaluation order: counter-account, payee, category. Within a
 * group the server's order stands (priority, then id); empty groups are left out.
 */
export function groupRules(rules: readonly Rule[]): RuleGroup[] {
	return SETS.map((sets) => ({ sets, rules: rules.filter((rule) => rule.sets === sets) })).filter(
		(group) => group.rules.length > 0
	);
}
