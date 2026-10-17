// The accounts list's order (ux/views/account.md): open accounts first in their sort order, then
// the closed ones. The server's order is not relied on.
import type { Account } from '#lib/types/domain.js';

export function orderAccounts(accounts: readonly Account[]): Account[] {
	return [...accounts].sort(
		(a, b) =>
			Number(a.closed_on !== null) - Number(b.closed_on !== null) ||
			a.sort_order - b.sort_order ||
			a.id - b.id
	);
}
