// The choices for what a rule sets (or the payee it conditions on), from the lookup lists.
import type { RuleSets } from '#lib/api/rules.js';
import type { Lookups } from '#lib/ledger/lookups.js';
import { categoryPath } from '#lib/theme/resolve.js';

export type TargetOption = { id: number; label: string };

/** The kind of row a target is: the lists differ, a counter-account is an account. */
export function targetOptions(
	kind: RuleSets,
	lookups: Lookups,
	keep: number | null
): TargetOption[] {
	let options: TargetOption[];
	if (kind === 'category') {
		options = [...lookups.categories.values()].map((c) => ({
			id: c.id,
			label: categoryPath(c, lookups.categories)
		}));
	} else if (kind === 'payee') {
		options = [...lookups.payees.values()].map((p) => ({ id: p.id, label: p.name }));
	} else {
		// a closed account cannot receive a transfer, but a rule that already names one keeps it
		options = [...lookups.accounts.values()]
			.filter((a) => a.closed_on === null || a.id === keep)
			.map((a) => ({ id: a.id, label: a.name }));
	}
	return options.sort((a, b) => a.label.localeCompare(b.label));
}

/** The words for a kind in a sentence: "category", "payee", "counter-account". */
export function kindWord(kind: RuleSets): string {
	return kind === 'counter_account' ? 'counter-account' : kind;
}
