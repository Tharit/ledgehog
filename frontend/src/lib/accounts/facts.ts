// The account's facts line (patterns §4.4, spec §3.11): data age, "balance not anchored" and the
// unexplained difference, as the quiet words under a balance. Nothing is computed here but words.
import {
	formatDate,
	formatMoney,
	formatReturn,
	relativeDay,
	type IsoDate
} from '#lib/format/index.js';
import { isInvestment } from '#lib/accounts/statement.js';
import type { Account, Money } from '#lib/types/domain.js';

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
	account: Pick<
		Account,
		'last_data_on' | 'anchored' | 'unexplained_difference' | 'synced' | 'kind'
	>,
	{ locale, today }: { locale: string; today: IsoDate }
): Fact[] {
	const facts: Fact[] = [];
	const date = dataDate(account);
	if (date === null) {
		facts.push({ id: 'age', text: 'Data: never' });
	} else {
		const age = relativeDay(date, today, locale);
		// a synced account's data comes from the sync; an unsynced one is valued (investment) or its
		// balance was set by hand
		const lead = account.synced
			? 'Data from'
			: isInvestment(account.kind)
				? 'Valued'
				: 'Balance set';
		facts.push({ id: 'age', text: `${lead} ${age.text}`, title: age.title });
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

/** What the return's help says where there is none: the client cannot tell the two reasons apart. */
export const NO_RETURN_HELP = 'Shown once the records span a year, and where a rate fits.';
export const NET_DEPOSITS_HELP =
	'The balance at the first record, plus what was paid in since, less what was taken out; not the cost of what is held.';

export type Performance = {
	netDepositsMoney: Money;
	gainMoney: Money;
	netDeposits: string;
	gain: string;
	/** "+6.2 % p.a.", or "—" where there is none yet */
	return: string;
	hasReturn: boolean;
	asOf: string | null;
};

/**
 * An investment account's performance (spec §8), as words; null on any other account and where
 * there is no record. The server leaves the facts null in those cases.
 */
export function describePerformance(
	account: Pick<Account, 'net_deposits' | 'gain' | 'return_rate' | 'return_as_of'>,
	{ locale }: { locale: string }
): Performance | null {
	const { net_deposits: net, gain } = account;
	if (net === null || gain === null) return null;
	const money = (m: { amount: number; currency: string }, showPlus: boolean) =>
		formatMoney(m.amount, m.currency, { locale, showCurrency: true, showPlus });
	const hasReturn = account.return_rate !== null;
	return {
		netDepositsMoney: net,
		gainMoney: gain,
		netDeposits: money(net, false),
		gain: money(gain, true),
		return: hasReturn ? `${formatReturn(account.return_rate, locale)} p.a.` : '—',
		hasReturn,
		asOf: account.return_as_of === null ? null : formatDate(account.return_as_of, locale)
	};
}
