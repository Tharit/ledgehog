// The accounts list's shape (ux/views/account.md): a group per kind with open accounts, in the order
// of spec §3.3, then the closed accounts; the accounts of a group in their sort order. The server
// says which groups there are and the sum of each one's balances per currency, never converted; its
// order is not relied on for the accounts.
import type { AccountGroup } from '#lib/api/types.js';
import { ACCOUNT_KINDS } from '#lib/accounts/kinds.js';
import { isInvestment } from '#lib/accounts/statement.js';
import { columnCurrency } from '#lib/format/index.js';
import type { Account, Money } from '#lib/types/domain.js';

export const CLOSED_GROUP = 'closed';

export function orderAccounts(accounts: readonly Account[]): Account[] {
	return [...accounts].sort(
		(a, b) =>
			Number(a.closed_on !== null) - Number(b.closed_on !== null) ||
			a.sort_order - b.sort_order ||
			a.id - b.id
	);
}

export type ListGroup = {
	/** the kind, or `closed` */
	key: string;
	label: string;
	accounts: Account[];
	/** the balances summed per currency, ordered by code, never converted */
	sums: Money[];
	/** the currency the group's accounts share, which its balance column names; null where mixed */
	currency: string | null;
	/** a depot or asset card, which adds the gain and return columns (spec §8) */
	investment: boolean;
};

/** The groups to draw: the server's, each with its accounts in sort order. */
export function groupAccounts(
	accounts: readonly Account[],
	groups: readonly AccountGroup[]
): ListGroup[] {
	const ordered = orderAccounts(accounts);
	const labels = new Map(ACCOUNT_KINDS.map(({ kind, label }) => [kind as string, label]));
	return groups.map((group) => {
		const kind = group.kind;
		const mine = ordered.filter((a) =>
			kind === null ? a.closed_on !== null : a.closed_on === null && a.kind === kind
		);
		return {
			key: kind ?? CLOSED_GROUP,
			label: kind === null ? 'Closed' : (labels.get(kind) ?? kind),
			accounts: mine,
			sums: group.sums,
			currency: columnCurrency(mine.map((a) => a.balance.currency)),
			investment: kind !== null && isInvestment(kind)
		};
	});
}
