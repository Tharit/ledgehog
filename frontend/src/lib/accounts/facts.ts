// The account's facts line (patterns §4.4, spec §3.11): data age, "balance not anchored" and the
// unexplained difference, as the quiet words under a balance. Nothing is computed here but words.
import {
	daysBetween,
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
 * coverage of a synced account, the latest balance record of an unsynced one and, on a clearance
 * account, the last day its balance was settled or of the other sign (spec §3.11); null is "never".
 */
export function dataDate(account: Pick<Account, 'last_data_on'>): string | null {
	return account.last_data_on;
}

/** The data age's words, which the Overview's card and the list's column show alone. */
export function describeDataAge(
	account: Parameters<typeof describeFacts>[0],
	context: { locale: string; today: IsoDate }
): Fact {
	return describeFacts(account, context)[0];
}

export function describeFacts(
	account: Pick<
		Account,
		'last_data_on' | 'anchored' | 'unexplained_difference' | 'synced' | 'kind' | 'balance'
	>,
	{ locale, today }: { locale: string; today: IsoDate }
): Fact[] {
	const facts: Fact[] = [];
	const date = dataDate(account);
	if (date === null) {
		facts.push({ id: 'age', text: 'Data: never' });
	} else if (account.kind === 'clearance') {
		// a clearance account has no records to age: what goes stale is its settling (spec §3.11)
		facts.push({
			id: 'age',
			text: account.balance.amount === 0 ? 'settled' : `open ${daysBetween(date, today)} d`,
			title: account.balance.amount === 0 ? undefined : `Open since ${formatDate(date, locale)}`
		});
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
export const PAID_IN_OUT_HELP =
	'Paid in since the start, less taken out; a sale counts as paid out by what it brought. Not the cost of what is held.';

export type Performance = {
	startBalanceMoney: Money;
	/** the anchor's date, as words */
	startOn: string;
	netMovementsMoney: Money;
	gainMoney: Money;
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
	account: Pick<
		Account,
		'start_balance' | 'start_on' | 'net_movements' | 'gain' | 'return_rate' | 'return_as_of'
	>,
	{ locale }: { locale: string }
): Performance | null {
	const { start_balance: start, start_on, net_movements: net, gain } = account;
	if (start === null || start_on === null || net === null || gain === null) return null;
	const money = (m: { amount: number; currency: string }, showPlus: boolean) =>
		formatMoney(m.amount, m.currency, { locale, showCurrency: true, showPlus });
	const hasReturn = account.return_rate !== null;
	return {
		startBalanceMoney: start,
		startOn: formatDate(start_on, locale),
		netMovementsMoney: net,
		gainMoney: gain,
		gain: money(gain, true),
		return: hasReturn ? `${formatReturn(account.return_rate, locale)} p.a.` : '—',
		hasReturn,
		asOf: account.return_as_of === null ? null : formatDate(account.return_as_of, locale)
	};
}
