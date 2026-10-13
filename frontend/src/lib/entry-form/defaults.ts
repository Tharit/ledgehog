// What the add form starts with (spec §3.9: today, the cash account, an expense) and what it
// remembers: the last account used, per viewer, in this browser only.
import type { Account } from '#lib/types/domain.js';

/** Only accounts without a bank connection take entries by hand (I40). */
export function entryAccounts(accounts: Iterable<Account>): Account[] {
	return [...accounts]
		.filter((account) => !account.synced)
		.sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name));
}

/**
 * The account the form starts on: the one the ledger is filtered to when it is exactly one, else
 * the last one used, else the only cash account, else none (the user chooses).
 */
export function defaultAccountId(
	available: readonly Account[],
	{
		filtered = [],
		lastUsed = null
	}: { filtered?: readonly number[]; lastUsed?: number | null } = {}
): number | null {
	const has = (id: number | null | undefined): id is number =>
		id !== null && id !== undefined && available.some((a) => a.id === id);
	if (filtered.length === 1 && has(filtered[0])) return filtered[0];
	if (has(lastUsed)) return lastUsed;
	const cash = available.filter((a) => a.kind === 'cash');
	return cash.length === 1 ? cash[0].id : null;
}

const key = (viewer: number | string | null) => `ledgehog.entry-form.account.${viewer ?? 'anon'}`;

export function readLastAccount(viewer: number | string | null): number | null {
	try {
		const raw = localStorage.getItem(key(viewer));
		const id = raw === null ? NaN : Number(raw);
		return Number.isInteger(id) ? id : null;
	} catch {
		return null;
	}
}

export function writeLastAccount(viewer: number | string | null, accountId: number): void {
	try {
		localStorage.setItem(key(viewer), String(accountId));
	} catch {
		// a private window or blocked site data: the form simply forgets
	}
}
