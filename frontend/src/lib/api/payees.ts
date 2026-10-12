// Payee writes (spec §3.6): create, update, delete and merge, previewed like the category ones.
import type { MergeControls } from './categories.js';
import { request } from './http.js';
import type {
	PayeeCreateBody,
	PayeeDeleteOut,
	PayeeMergeOut,
	PayeeUpdateBody,
	PayeeWriteOut
} from './types.js';

export function createPayee(body: PayeeCreateBody): Promise<PayeeWriteOut> {
	return request('POST', '/api/ledger/payees', { body });
}

/** Absent fields stay; `null` clears the note, icon, colour or document provider. */
export function updatePayee(id: number, body: PayeeUpdateBody): Promise<PayeeWriteOut> {
	return request('PUT', `/api/ledger/payees/${id}`, { body });
}

/** Refused with 409 `payee_in_use` while an entry references it; deleting takes its rules with it. */
export function deletePayee(
	id: number,
	{ dryRun = false }: { dryRun?: boolean } = {}
): Promise<PayeeDeleteOut> {
	return request('DELETE', `/api/ledger/payees/${id}`, { query: { dry_run: dryRun } });
}

export function mergePayee(
	id: number,
	into: number,
	{ dryRun = false, expectedCount }: MergeControls = {}
): Promise<PayeeMergeOut> {
	return request('POST', `/api/ledger/payees/${id}/merge`, {
		body: { into, dry_run: dryRun, expected_count: expectedCount ?? null }
	});
}
