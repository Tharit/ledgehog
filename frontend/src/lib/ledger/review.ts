// What a review token (patterns §4.2) is called and what it means to the user.
import { REVIEW_FLAGS } from './filter.js';

export const REVIEW_FLAG_INFO: Readonly<Record<string, { name: string; sentence: string }>> = {
	unconfirmed: { name: 'Unconfirmed', sentence: 'Values are proposals' },
	unclassified: { name: 'Unclassified', sentence: 'Type or category missing' },
	document_suggested: { name: 'Document suggested', sentence: 'A document may explain this' },
	waiting: { name: 'Waiting', sentence: 'Partner or document still expected' },
	unmatched_transfer: { name: 'Unmatched transfer', sentence: 'Transfer leg without a partner' }
};

/** The tokens in the order the badges and the filter list them. */
export const REVIEW_FLAG_ORDER: readonly string[] = REVIEW_FLAGS;
