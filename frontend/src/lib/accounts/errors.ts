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
