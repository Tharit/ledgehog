// The kinds an account can have (spec §3.3), in the order the Add account dialog lists them.
import type { AccountKind } from '#lib/api/types.js';

export const ACCOUNT_KINDS: readonly { kind: AccountKind; label: string }[] = [
	{ kind: 'checking', label: 'Checking' },
	{ kind: 'savings', label: 'Savings' },
	{ kind: 'card', label: 'Card' },
	{ kind: 'cash', label: 'Cash' },
	{ kind: 'digital_wallet', label: 'Digital wallet' },
	{ kind: 'depot', label: 'Depot' },
	{ kind: 'loan', label: 'Loan' },
	{ kind: 'asset', label: 'Asset' }
];

/** What a new account is unless the caller knows better: money held by hand. */
export const DEFAULT_KIND: AccountKind = 'cash';
