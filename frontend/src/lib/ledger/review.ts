// What a review token (patterns §4.2) is called and what it means to the user.
import { REVIEW_FLAGS } from './filter.js';

export const REVIEW_FLAG_INFO: Readonly<Record<string, { name: string; sentence: string }>> = {
	unconfirmed: { name: 'Unconfirmed', sentence: 'Values are proposals' },
	unclassified: { name: 'Unclassified', sentence: 'Type or category missing' },
	waiting: { name: 'Waiting', sentence: 'Partner still expected' },
	unmatched_transfer: { name: 'Unmatched transfer', sentence: 'Transfer leg without a partner' }
};

/** The tokens in the order the badges and the filter list them. */
export const REVIEW_FLAG_ORDER: readonly string[] = REVIEW_FLAGS;

/** The part of an entry a badge's sentence depends on. */
export type BadgeSubject = {
	type: string | null;
	counterpart_entry_id: number | null;
};

/**
 * The sentence a badge carries: `waiting` on a transfer leg without a partner names the partner.
 */
export function reviewSentence(flag: string, subject?: BadgeSubject | null): string | undefined {
	if (flag === 'waiting' && subject?.type === 'transfer' && subject.counterpart_entry_id === null)
		return 'Its partner has probably not been imported yet';
	return REVIEW_FLAG_INFO[flag]?.sentence;
}
