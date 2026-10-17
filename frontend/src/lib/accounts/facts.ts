// The account's facts line (patterns §4.4, spec §3.11): data age, "balance not anchored" and the
// unexplained difference, as the quiet words under a balance. Nothing is computed here but words.
import { formatMoney, relativeDay, type IsoDate } from '#lib/format/index.js';
import type { Account } from '#lib/types/domain.js';

export type Fact = { id: 'age' | 'anchor' | 'difference'; text: string; title?: string };

/**
 * The date the account's data age counts from: the server's `last_data_on`, which is the sync
 * coverage of a synced account and the latest balance record of an unsynced one (spec §3.11);
 * null is "never".
 */
export function dataDate(account: Pick<Account, 'last_data_on'>): string | null {
	return account.last_data_on;
}

export function describeFacts(
	account: Pick<Account, 'last_data_on' | 'anchored' | 'unexplained_difference'>,
	{ locale, today }: { locale: string; today: IsoDate }
): Fact[] {
	const facts: Fact[] = [];
	const date = dataDate(account);
	if (date === null) {
		facts.push({ id: 'age', text: 'Data: never' });
	} else {
		const age = relativeDay(date, today, locale);
		facts.push({ id: 'age', text: `Data from ${age.text}`, title: age.title });
	}
	if (!account.anchored) {
		facts.push({
			id: 'anchor',
			text: 'Balance not anchored',
			title: 'No balance record yet: the balance starts from zero'
		});
	}
	const difference = account.unexplained_difference;
	if (difference !== null && difference.amount !== 0) {
		facts.push({
			id: 'difference',
			text: `Unexplained difference ${formatMoney(difference.amount, difference.currency, { locale })}`,
			title: 'How far the ledger and the bank disagree as of the latest reported balance'
		});
	}
	return facts;
}
