import { request } from './http.js';
import type { Account, AccountCreateBody, AccountWriteOut } from './types.js';

export async function listAccounts(signal?: AbortSignal): Promise<Account[]> {
	const { accounts } = await request<{ accounts: Account[] }>('GET', '/api/ledger/accounts', {
		signal
	});
	return accounts;
}

/**
 * A new account, entered by hand (spec §3.3). The answer holds the account as it now stands and
 * the settle result. 409 `conflict` (`details.reason` `duplicate_external_ref`), 422
 * `validation_error` (an unknown currency says `details.reason` `unknown_currency`).
 */
export function createAccount(body: AccountCreateBody): Promise<AccountWriteOut> {
	return request('POST', '/api/ledger/accounts', { body });
}
