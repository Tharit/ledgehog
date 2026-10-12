// How a failed list fetch is presented, routed by the error's `code` and never by its message
// (architecture §4.4, patterns §8).

export type LoadErrorPresentation = { title: string; message: string; retryable: boolean };

export function describeLoadError(code: string): LoadErrorPresentation {
	switch (code) {
		case 'network_error':
			return {
				title: 'The ledger could not be loaded',
				message: 'The server could not be reached. Check the connection and try again.',
				retryable: true
			};
		case 'validation_error':
			return {
				title: 'This filter is not valid',
				message: 'The server did not accept these filters. Clear them and try again.',
				retryable: false
			};
		case 'unauthenticated':
			return {
				title: 'You are signed out',
				message: 'Your session has ended. Sign in again to see the ledger.',
				retryable: false
			};
		default:
			return {
				title: 'The ledger could not be loaded',
				message: 'The server could not answer this request. Try again in a moment.',
				retryable: true
			};
	}
}

/** What a derived entry's tagging refusal says; also shown when `t` is pressed on one. */
export const DERIVED_NOT_TAGGABLE = 'Derived entries cannot be tagged';

/** Said after a write whose derived figures could not be recomputed (patterns §8). */
export const SETTLE_STALE = 'Derived figures may be stale until the next action.';

/**
 * How a failed tag write is put to the user, routed by the error's `code` and, for a conflict, its
 * `details.reason` — never by the message (architecture §4.4, patterns §8).
 */
export function describeTagError(error: { code: string; details?: unknown }): string {
	const reason = (error.details as { reason?: unknown } | null | undefined)?.reason;
	switch (error.code) {
		case 'not_found':
			return 'That entry or tag no longer exists. Refresh the page to see the current state.';
		case 'conflict':
			if (reason === 'derived_entry') return DERIVED_NOT_TAGGABLE;
			if (reason === 'duplicate_name') {
				return 'A tag with that name already exists. Refresh the page to see it.';
			}
			if (reason === 'filter_result_changed') {
				return 'The result changed. Check it and confirm again.';
			}
			return 'Someone changed this meanwhile. Refresh the page and try again.';
		case 'validation_error':
			return 'The server did not accept this. Check the filter or the name and try again.';
		case 'network_error':
			return 'The server could not be reached. Check the connection and try again.';
		case 'unauthenticated':
			return 'Your session has ended. Sign in again.';
		default:
			return 'The server could not do this. Try again in a moment.';
	}
}
