// How a refused "Add account" is understood and said, routed by the error's `code` and, for a 409
// `conflict`, its `details.reason`, never by its message (architecture §4.4, patterns §8).
import { ApiError } from '#lib/api/index.js';

export type AccountFailure =
	| { kind: 'duplicate_external_ref' }
	| { kind: 'unknown_currency' }
	| { kind: 'validation' }
	| { kind: 'network' }
	| { kind: 'unauthenticated' }
	| { kind: 'other' };

function reasonOf(details: unknown): unknown {
	return details !== null && typeof details === 'object' && !Array.isArray(details)
		? (details as Record<string, unknown>).reason
		: undefined;
}

export function classifyAccountError(error: unknown): AccountFailure {
	if (!(error instanceof ApiError)) return { kind: 'network' };
	switch (error.code) {
		case 'conflict':
			return reasonOf(error.details) === 'duplicate_external_ref'
				? { kind: 'duplicate_external_ref' }
				: { kind: 'other' };
		case 'validation_error':
			return reasonOf(error.details) === 'unknown_currency'
				? { kind: 'unknown_currency' }
				: { kind: 'validation' };
		case 'network_error':
			return { kind: 'network' };
		case 'unauthenticated':
			return { kind: 'unauthenticated' };
		default:
			return { kind: 'other' };
	}
}

/** Where the message stands: under the field it came from, or in the dialog's feedback slot. */
export function failureField(failure: AccountFailure): 'name' | 'currency' | null {
	if (failure.kind === 'validation') return 'name';
	if (failure.kind === 'unknown_currency') return 'currency';
	return null;
}

export function describeAccountFailure(failure: AccountFailure): string {
	switch (failure.kind) {
		case 'duplicate_external_ref':
			return 'Another account already uses this bank reference.';
		case 'unknown_currency':
			return 'This currency is not known.';
		case 'validation':
			return 'The server did not accept this name. Check it and try again.';
		case 'network':
			return 'The server could not be reached. Check the connection and try again.';
		case 'unauthenticated':
			return 'Your session has ended. Sign in again.';
		default:
			return 'The account could not be added. Try again in a moment.';
	}
}

/** A refused write from the account page, routed by `code` and `details.reason` (patterns §8). */
export type WriteFailure = {
	/** `error`: nothing was written. `conflict`: the world moved; ask again. */
	kind: 'error' | 'conflict';
	text: string;
	/** `details.reason` of a 409, for the caller that tells reasons apart */
	reason?: string;
	/** what an account holds (`account_not_empty`), by name */
	held?: Readonly<Record<string, number>>;
	retryable: boolean;
};

function heldOf(details: unknown): Record<string, number> | undefined {
	const held =
		details !== null && typeof details === 'object' && !Array.isArray(details)
			? (details as Record<string, unknown>).held
			: undefined;
	if (held === null || typeof held !== 'object' || Array.isArray(held)) return undefined;
	return Object.fromEntries(
		Object.entries(held).filter((entry): entry is [string, number] => typeof entry[1] === 'number')
	);
}

/** What a version conflict says: the entries a write would change were edited since its preview. */
export const ENTRIES_CHANGED =
	'The entries this would change were edited since the preview. The preview is updated: check it and try again.';

function hasEntryIds(details: unknown): boolean {
	const ids =
		details !== null && typeof details === 'object' && !Array.isArray(details)
			? (details as Record<string, unknown>).entry_ids
			: undefined;
	return Array.isArray(ids);
}

const REASONS: Record<string, string> = {
	duplicate_external_ref: 'Another account already uses this bank reference.',
	record_date_taken: 'Another balance record already holds this date.',
	reported_record_not_editable: 'A reported balance cannot be edited. Delete it instead.',
	already_duplicate: 'This row is already marked as a duplicate.',
	duplicate_chain: 'The other row is itself a duplicate: pick its original instead.',
	not_a_duplicate: 'This row is not marked as a duplicate.',
	not_revertible: 'Only the latest successful run of an account can be reverted.'
};

export function classifyWriteError(error: unknown): WriteFailure {
	if (!(error instanceof ApiError) || error.code === 'network_error') {
		return {
			kind: 'error',
			text: 'The server could not be reached. Check the connection and try again.',
			retryable: true
		};
	}
	switch (error.code) {
		case 'unauthenticated':
			return { kind: 'error', text: 'Your session has ended. Sign in again.', retryable: false };
		case 'not_found':
			return {
				kind: 'error',
				text: 'This no longer exists. Reload the page to see what is there now.',
				retryable: false
			};
		case 'try_again':
			return {
				kind: 'error',
				text: 'The server was busy and did not write this. Try again.',
				retryable: true
			};
		case 'conflict': {
			const reason = reasonOf(error.details);
			if (reason === 'account_not_empty') {
				const held = heldOf(error.details);
				const what = held
					? Object.entries(held)
							.map(([name, n]) => `${n} ${name}`)
							.join(', ')
					: 'data';
				return {
					kind: 'error',
					reason: 'account_not_empty',
					held,
					text: `This account holds ${what}, so it cannot be deleted. Closing it keeps its history.`,
					retryable: false
				};
			}
			// a 409 that names entries: they were written since the preview that reported their versions
			if (reason === undefined && hasEntryIds(error.details)) {
				return {
					kind: 'conflict',
					reason: 'entries_changed',
					text: ENTRIES_CHANGED,
					retryable: false
				};
			}
			const known = typeof reason === 'string' ? REASONS[reason] : undefined;
			return {
				kind: 'conflict',
				reason: typeof reason === 'string' ? reason : undefined,
				text:
					known ??
					'This account changed since you opened this dialog. The figures are updated: check them and try again.',
				retryable: false
			};
		}
		case 'not_revertible':
		case 'not_latest_run':
			return {
				kind: 'conflict',
				reason: 'not_revertible',
				text: REASONS.not_revertible,
				retryable: false
			};
		case 'invalid_duplicate':
			return {
				kind: 'error',
				text: 'These two rows cannot stand in this relation.',
				retryable: false
			};
		case 'validation_error':
			return {
				kind: 'error',
				text: 'The server did not accept these values. Check them and try again.',
				retryable: false
			};
		default:
			return {
				kind: 'error',
				text: 'The server could not do this. Try again in a moment.',
				retryable: true
			};
	}
}
