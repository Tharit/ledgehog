import { request } from './http.js';
import type { Account } from './types.js';

export async function listAccounts(signal?: AbortSignal): Promise<Account[]> {
	const { accounts } = await request<{ accounts: Account[] }>('GET', '/api/ledger/accounts', {
		signal
	});
	return accounts;
}
