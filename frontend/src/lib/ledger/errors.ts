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
