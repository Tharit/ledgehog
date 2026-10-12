// What a payee merge or delete preview says, in words (patterns §6, spec §3.6).
import { describeHeld } from '#lib/dimensions/errors.js';
import { plural } from '#lib/dimensions/text.js';
import type { Payee, PayeeDeleteOut, PayeeMergeOut } from '#lib/types/domain.js';

export type PayeeMergeSummary = {
	totals: string;
	/** rules that set the payee, rules that name it as a condition: 0 entries are left out */
	rules: string[];
	/** warnings: the source's document provider would be lost */
	warnings: string[];
	notes: string[];
};

export function payeeMergeSummary(
	out: PayeeMergeOut,
	source: Payee | undefined
): PayeeMergeSummary {
	const setting = out.setting_rule_ids.length;
	const naming = out.condition_rule_ids.length;
	const warnings: string[] = [];
	if (out.document_provider_lost) {
		warnings.push(
			`${source?.name ?? 'The merged payee'} names the document provider "${out.source_document_provider ?? ''}"; ${out.target.name} does not, so it would be lost.`
		);
	}
	return {
		totals: `Repoints ${plural(out.entry_count, 'entry', 'entries')}`,
		rules: [
			...(setting > 0 ? [`${plural(setting, 'rule', 'rules')} setting it repointed`] : []),
			...(naming > 0
				? [`${plural(naming, 'rule', 'rules')} naming it as a condition repointed`]
				: [])
		],
		warnings,
		notes: [
			'Nothing returns to review.',
			`${out.target.name} keeps its own name, note, icon and colour.`
		]
	};
}

export type PayeeDeleteSummary = {
	deletable: boolean;
	reason: string;
	/** "Rule name (sets the payee)" lines, the rules the delete would take with it */
	rules: string[];
};

const ROLES: Record<string, string> = {
	sets: 'sets this payee',
	condition: 'names this payee as a condition'
};

export function payeeDeleteSummary(out: PayeeDeleteOut): PayeeDeleteSummary {
	return {
		deletable: out.deletable,
		reason: out.deletable
			? ''
			: `${out.payee.name} cannot be deleted: it is referenced by ${describeHeld(out.held)}. Merge it into another payee instead.`,
		rules: out.rules.map((r) => `${r.name} (${ROLES[r.role] ?? r.role})`)
	};
}

/** The list indexed by id. */
export function indexPayees(payees: readonly Payee[]): Map<number, Payee> {
	return new Map(payees.map((p) => [p.id, p]));
}
