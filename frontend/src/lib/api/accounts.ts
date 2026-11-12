import { request } from './http.js';
import type {
	Account,
	AccountList,
	AccountCreateBody,
	AccountUpdateBody,
	AccountWriteOut,
	Money,
	RecordDeleteOut,
	RecordWriteOut,
	SettleOut
} from './types.js';

/** The accounts, and each group's total at today's rate (the accounts list's group rows). */
export function listAccountGroups(signal?: AbortSignal): Promise<AccountList> {
	return request<AccountList>('GET', '/api/ledger/accounts', { signal });
}

export async function listAccounts(signal?: AbortSignal): Promise<Account[]> {
	return (await listAccountGroups(signal)).accounts;
}

/**
 * A new account, entered by hand (spec §3.3). The answer holds the account as it now stands and
 * the settle result. 409 `conflict` (`details.reason` `duplicate_external_ref`), 422
 * `validation_error` (an unknown currency says `details.reason` `unknown_currency`).
 */
export function createAccount(body: AccountCreateBody): Promise<AccountWriteOut> {
	return request('POST', '/api/ledger/accounts', { body });
}

/** What an edit changes: absent fields stay; `null` clears a note, reference, icon or colour. */
export function updateAccount(id: number, body: AccountUpdateBody): Promise<AccountWriteOut> {
	return request('PUT', `/api/ledger/accounts/${id}`, { body });
}

/** Close the account on a date; it stops fetching and holds no balance (spec §3.3). */
export function closeAccount(id: number, closedOn: string): Promise<AccountWriteOut> {
	return request('POST', `/api/ledger/accounts/${id}/close`, { body: { closed_on: closedOn } });
}

export function reopenAccount(id: number): Promise<AccountWriteOut> {
	return request('POST', `/api/ledger/accounts/${id}/reopen`);
}

/**
 * Delete an account that holds nothing. 409 `conflict` with `details.reason` `account_not_empty`
 * and `details.held` (what it holds, by name) otherwise.
 */
export function deleteAccount(id: number): Promise<{ settle: SettleOut }> {
	return request('DELETE', `/api/ledger/accounts/${id}`);
}

/**
 * "Set balance": a manual record on a date; a date that already holds one edits it (spec §5.10).
 * 422 `validation_error` for another currency.
 */
export function setBalance(
	accountId: number,
	body: { balance_on: string; balance: Money }
): Promise<RecordWriteOut> {
	return request('POST', `/api/ledger/accounts/${accountId}/balance-records`, { body });
}

/** Correct a manual record: its balance, and its date when given. 409 `record_date_taken`. */
export function correctBalance(
	recordId: number,
	body: { balance: Money; balance_on?: string }
): Promise<RecordWriteOut> {
	return request('PUT', `/api/ledger/balance-records/${recordId}`, { body });
}

/** Delete any record, reported ones included; its interval merges into the next (spec §3.10). */
export function deleteBalanceRecord(recordId: number): Promise<RecordDeleteOut> {
	return request('DELETE', `/api/ledger/balance-records/${recordId}`);
}
