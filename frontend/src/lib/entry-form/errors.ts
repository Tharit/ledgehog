// How a failed entry-form write or dry run is understood and put to the user: routed by the error's
// `code` and `details`, never by its message (architecture §4.4, patterns §8).
import type { FieldName } from './validate.js';

export type Failure =
	/** under a field (patterns §11.5) */
	| { kind: 'field'; field: FieldName; text: string; reloadLookups?: boolean }
	/** nothing was written; the dialog says so */
	| { kind: 'error'; text: string; retryable: boolean }
	/** the world moved: ask again with the new numbers (patterns §8) */
	| { kind: 'conflict'; text: string }
	/** the row is gone */
	| { kind: 'gone'; text: string }
	/** the id was taken by another row: the next submission needs a new one */
	| { kind: 'id_taken'; text: string };

type ErrorLike = { code: string; details?: unknown };

function record(value: unknown): Record<string, unknown> {
	return value !== null && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

const FIELD_OF: Record<string, FieldName> = {
	account_id: 'account',
	booked_on: 'date',
	amount: 'amount',
	purpose: 'purpose'
};

function validationFailure(details: unknown): Failure {
	if (Array.isArray(details)) {
		for (const item of details) {
			const found = record(item);
			const location = Array.isArray(found.location) ? found.location : [];
			const field = FIELD_OF[String(location[location.length - 1])];
			if (field) {
				const message = typeof found.message === 'string' && found.message ? found.message : null;
				return { kind: 'field', field, text: message ?? 'The server did not accept this value.' };
			}
		}
	}
	return {
		kind: 'error',
		text: 'The server did not accept this. Check the values and try again.',
		retryable: false
	};
}

export function classifyEntryError(error: ErrorLike): Failure {
	const details = record(error.details);
	switch (error.code) {
		case 'account_synced':
			return {
				kind: 'field',
				field: 'account',
				text: 'Entries are added by hand only on accounts without a bank connection.'
			};
		case 'stale_reference':
			return {
				kind: 'field',
				field: 'account',
				text: 'This account no longer exists. The list of accounts has been reloaded; choose another.',
				reloadLookups: true
			};
		case 'conflict':
			if (details.reason === 'id_taken') {
				return { kind: 'id_taken', text: 'That did not go through. Try again.' };
			}
			return {
				kind: 'conflict',
				text: 'This entry changed since you opened it. What would happen is checked again below.'
			};
		case 'try_again':
			return {
				kind: 'error',
				text: 'The ledger was busy and nothing was written. Try again.',
				retryable: true
			};
		case 'not_found':
			return { kind: 'gone', text: 'This entry no longer exists.' };
		case 'not_user_authored':
			return {
				kind: 'gone',
				text: 'Only entries added by hand can be edited or deleted here.'
			};
		case 'validation_error':
			return validationFailure(error.details);
		case 'network_error':
			return {
				kind: 'error',
				text: 'The server could not be reached. Nothing was written. Try again.',
				retryable: true
			};
		default:
			return {
				kind: 'error',
				text: 'The server could not do this. Try again in a moment.',
				retryable: true
			};
	}
}
