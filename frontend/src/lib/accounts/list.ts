// The accounts list's shape (ux/views/account.md): a group per kind with open accounts, in the order
// of spec §3.3, then the closed accounts; the accounts of a group in their sort order. The server
// says which groups there are and what each is worth at today's rate; its order is not relied on
// for the accounts.
import type { AccountGroup } from '#lib/api/types.js';
import { ACCOUNT_KINDS } from '#lib/accounts/kinds.js';
import { netWorthCell, type BalanceCell } from '#lib/reports/tables.js';
import type { Account } from '#lib/types/domain.js';

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
	/** the accounts' total in the base currency, or what it leaves out */
	total: BalanceCell;
};

/** The groups to draw: the server's, each with its accounts in sort order. */
export function groupAccounts(
	accounts: readonly Account[],
	groups: readonly AccountGroup[],
	baseCurrency: string
): ListGroup[] {
	const ordered = orderAccounts(accounts);
	const labels = new Map(ACCOUNT_KINDS.map(({ kind, label }) => [kind as string, label]));
	return groups.map((group) => {
		const kind = group.kind;
		return {
			key: kind ?? CLOSED_GROUP,
			label: kind === null ? 'Closed' : (labels.get(kind) ?? kind),
			accounts: ordered.filter((a) =>
				kind === null ? a.closed_on !== null : a.closed_on === null && a.kind === kind
			),
			total: netWorthCell(group.net_worth, baseCurrency)
		};
	});
}
