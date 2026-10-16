// How a document is named in the views: merchant and title, whichever it has.
import type { DocumentRow } from '#lib/types/domain.js';

export function documentTitle(
	document: Pick<DocumentRow, 'merchant_name' | 'title' | 'provider'>
): string {
	const parts = [document.merchant_name, document.title].filter(
		(part): part is string => part !== null && part.trim() !== ''
	);
	return parts.length > 0 ? parts.join(' · ') : `${document.provider} document`;
}

export type DocumentFailure = { title: string; message: string; retryable: boolean };

/** A failed read in words, routed by code (patterns §8); `what` is "documents" or "document". */
export function describeDocumentError(
	code: string,
	what: 'documents' | 'document'
): DocumentFailure {
	const title = `The ${what} could not be loaded`;
	switch (code) {
		case 'not_found':
			return {
				title: 'This document does not exist',
				message: 'It may have been removed. Go back to the list of documents.',
				retryable: false
			};
		case 'network_error':
			return {
				title,
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
				message: `Your session has ended. Sign in again to see the ${what}.`,
				retryable: false
			};
		default:
			return {
				title,
				message: 'The server could not answer this request. Try again in a moment.',
				retryable: true
			};
	}
}
