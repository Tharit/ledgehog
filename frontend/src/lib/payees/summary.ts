// What a payee merge or delete preview says, in words (patterns §6, spec §3.6).
import { describeHeld } from '#lib/dimensions/errors.js';
import { plural } from '#lib/dimensions/text.js';
import type { Payee, PayeeDeleteOut, PayeeMergeOut } from '#lib/types/domain.js';

export type PayeeMergeSummary = {
	totals: string;
	/** rules that set the payee, rules that name it as a condition: 0 entries are left out */
	rules: string[];
	notes: string[];
};

export function payeeMergeSummary(out: PayeeMergeOut): PayeeMergeSummary {
	const setting = out.setting_rule_ids.length;
	const naming = out.condition_rule_ids.length;
	return {
		totals: `Repoints ${plural(out.entry_count, 'entry', 'entries')}`,
		rules: [
			...(setting > 0 ? [`${plural(setting, 'rule', 'rules')} setting it repointed`] : []),
			...(naming > 0
				? [`${plural(naming, 'rule', 'rules')} naming it as a condition repointed`]
				: [])
		],
		notes: [
			'Nothing returns to review.',
			`${out.target.name} keeps its own name, note, icon and colour.`
		]
	};
}

/** A sentence that counts rules, and their names to list under it. */
export type RuleGroup = { heading: string; names: string[] };

export type PayeeDeleteSummary = {
	deletable: boolean;
	reason: string;
	/** the rules that set this payee: the delete takes them with it */
	deleted: RuleGroup | null;
	/** the rules that only test this payee: they stay, and stop matching */
	dangling: RuleGroup | null;
};

function group(
	rules: readonly { name: string }[],
	verb: [one: string, many: string],
	rest: string
): RuleGroup | null {
	if (rules.length === 0) return null;
	const count = plural(rules.length, 'rule', 'rules');
	return {
		heading: `${count} ${rules.length === 1 ? verb[0] : verb[1]} this payee ${rest}:`,
		names: rules.map((r) => r.name)
	};
}

export function payeeDeleteSummary(out: PayeeDeleteOut): PayeeDeleteSummary {
	return {
		deletable: out.deletable,
		reason: out.deletable
			? ''
			: `${out.payee.name} cannot be deleted: it is referenced by ${describeHeld(out.held)}. Merge it into another payee instead.`,
		deleted: group(out.rules, ['sets', 'set'], 'and will be deleted'),
		dangling: group(out.dangling_rules, ['tests', 'test'], 'and will stop matching')
	};
}

/** The list indexed by id. */
export function indexPayees(payees: readonly Payee[]): Map<number, Payee> {
	return new Map(payees.map((p) => [p.id, p]));
}
