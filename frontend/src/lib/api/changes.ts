// What changed (architecture §4.2): the change values of the ledger, the documents and each account,
// and the user's active task. A value is opaque: it is compared with the one seen, never read.
import { request } from './http.js';

type Schemas = import('../types/api.js').components['schemas'];

/** The change read: the values plus the current user's active task (or null). */
export type ChangeRead = Schemas['ChangesOut'];

/** The values alone, as every write's response header carries them. */
export type ChangeValues = Pick<ChangeRead, 'ledger' | 'documents' | 'accounts'>;

export function readChanges(signal?: AbortSignal): Promise<ChangeRead> {
	return request('GET', '/api/changes', { signal });
}
