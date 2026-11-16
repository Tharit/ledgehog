// The choices for what a rule sets (or the payee it conditions on), from the lookup lists.
import type { RuleSets } from '#lib/api/rules.js';
import type { Lookups } from '#lib/ledger/lookups.js';
import { categoryPath } from '#lib/theme/resolve.js';

export type TargetOption = { id: number; label: string };

/** The kind of row a target is: the lists differ, a counter-account is an account. */
export function targetOptions(kind: RuleSets, lookups: Lookups): TargetOption[] {
	let options: TargetOption[];
	if (kind === 'category') {
		options = [...lookups.categories.values()].map((c) => ({
			id: c.id,
			label: categoryPath(c, lookups.categories)
		}));
	} else if (kind === 'payee') {
		options = [...lookups.payees.values()].map((p) => ({ id: p.id, label: p.name }));
	} else {
		// every account is listed, the open ones first and the closed ones after (spec §3.3); whether
		// an account can take this entry is the preview's to say
		const byName = (x: TargetOption, y: TargetOption) => x.label.localeCompare(y.label);
		const accounts = [...lookups.accounts.values()];
		const open = accounts.filter((a) => a.closed_on === null);
		const closed = accounts.filter((a) => a.closed_on !== null);
		return [open, closed].flatMap((part) =>
			part.map((a) => ({ id: a.id, label: a.name })).sort(byName)
		);
	}
	return options.sort((a, b) => a.label.localeCompare(b.label));
}

/** The words for a kind in a sentence: "category", "payee", "counter-account". */
export function kindWord(kind: RuleSets): string {
	return kind === 'counter_account' ? 'counter-account' : kind;
}
