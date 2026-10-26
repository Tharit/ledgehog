// What a problem code of a preview or a refused commit says, in plain words (patterns §6, §8:
// "invalid is shown, not blocked", with the remedy the spec gives where it gives one). The server
// sends a code and numbers, never prose; the words are here.
import { formatMoney } from '#lib/format/index.js';
import type { SuggestedSplit, UnitProblem } from './types.js';

export type ProblemText = {
	text: string;
	/** what to do about it, where the spec says */
	remedy?: string;
};

export type ProblemContext = {
	/** the currency of an entry's source, for the amounts a problem names */
	currency: (entryId: number | null) => string;
	locale: string;
	/** the window the offers were listed for when it was widened (days), else null */
	windowDays?: number | null;
	/** the currency of the account a leg's counter-leg would be created in, when known */
	counterCurrency?: (entryId: number | null) => string | null;
	/** the kind of the account an entry's counter-account is, when known */
	counterKind?: (entryId: number | null) => string | null;
};

/** What a draft that changes a booking's type, amount or split, or removes its entry, is told (spec §5.8). */
export const BOOKING_FIXED =
	'A booking’s type, amount and split are its source’s: they cannot be changed here.';

const NUMBER_DETAIL = (detail: UnitProblem['detail'], key: string): number | null => {
	const value = detail[key];
	return typeof value === 'number' ? value : null;
};

function stale(field: string | null): string {
	if (field === 'category_id') return 'The category you chose no longer exists.';
	if (field === 'payee_id') return 'The payee you chose no longer exists.';
	return 'The account you chose no longer exists.';
}

export function describeProblem(problem: UnitProblem, context: ProblemContext): ProblemText {
	const { detail } = problem;
	const money = (minor: number | null) =>
		minor === null
			? ''
			: formatMoney(Math.abs(minor), context.currency(problem.entry_id), {
					locale: context.locale,
					showPlus: false
				});
	switch (problem.code) {
		case 'amount_zero':
			return { text: 'An entry is never for nothing.' };
		case 'residual_zero':
			return {
				text: 'The split leaves nothing for the original entry.',
				remedy: 'Make the new amounts smaller, or remove one.'
			};
		case 'residual_sign_flip':
			return {
				text: 'The new amounts add up to more than the transaction.',
				remedy: 'Make the new amounts smaller, or remove one.'
			};
		case 'second_transfer':
			return {
				text: 'Only one entry of a transaction can be a transfer.',
				remedy: 'Make the other one a flow.'
			};
		case 'new_entry_not_flow':
			return { text: 'A new split entry is always a flow.' };
		case 'type_conflict':
			return {
				text:
					problem.field === 'counter_account'
						? 'A flow has no counter-account.'
						: 'A transfer has no category or payee.'
			};
		case 'currency_rule': {
			const required = typeof detail.required === 'string' ? detail.required : '';
			const actual = typeof detail.actual === 'string' ? detail.actual : '';
			// a clearance account takes a charge only in its own currency (spec §5.7)
			if (context.counterKind?.(problem.entry_id) === 'clearance')
				return {
					text: `A clearance account takes only charges in its own currency (${actual}); this charge is in ${required}.`,
					remedy: `Choose an account in ${required}.`
				};
			return {
				text: `This transfer needs an account in ${required}, not ${actual}.`,
				remedy: `Choose an account in ${required}.`
			};
		}
		case 'own_counter_account':
			return { text: 'A transfer cannot go to its own account.' };
		case 'pair_unequal':
			return {
				text: `The two legs of this transfer differ by ${money(NUMBER_DETAIL(detail, 'difference'))}.`,
				remedy: 'Split the difference off the larger leg as a flow, or pick another partner.'
			};
		case 'pair_sign':
			return {
				text: 'The two legs of a transfer must move money in opposite directions.',
				remedy: 'Pick another partner.'
			};
		case 'partner_not_offered':
			return {
				text: 'This entry is not offered as a partner (wrong account, direction or date).',
				remedy: context.windowDays
					? 'Pick another partner.'
					: 'Pick another partner, or load more candidates in the list.'
			};
		case 'partner_in_unit':
			return { text: 'This entry is already part of this unit.' };
		case 'received_amount_required': {
			const named = typeof detail.currency === 'string' ? detail.currency : null;
			const currency = named ?? context.counterCurrency?.(problem.entry_id) ?? null;
			return {
				text: currency ? `Enter the amount received in ${currency}.` : 'Enter the amount received.'
			};
		}
		case 'received_amount_not_needed':
			return { text: 'No amount is needed: both sides are in the same currency.' };
		case 'counter_leg_not_offered':
			return {
				text: 'The other side cannot be created here: this leg already has a partner, the counter-account is unknown, or it is a clearance account, whose other side is booked from the charge.'
			};
		case 'clearance_transfer':
			return {
				text: 'An entry on a clearance account is a transfer only as a booking.',
				remedy: 'Make it a flow.'
			};
		case 'booking_fixed':
			return { text: BOOKING_FIXED };
		case 'counter_leg_account_synced':
			return {
				text: 'The other side cannot be created by hand on a synced account: it arrives with its import.'
			};
		case 'split_sum':
			return {
				text: `The entries do not add up to the transaction: they are off by ${money(NUMBER_DETAIL(detail, 'difference'))}.`
			};
		case 'stale_reference':
			return { text: stale(problem.field), remedy: 'Choose again.' };
		case 'invariant_violated':
			return { text: 'This change would break a rule of the ledger.' };
		default:
			return { text: 'This change cannot be committed.' };
	}
}

/** One sentence: the problem and, where there is one, its remedy. */
export function problemSentence(text: ProblemText): string {
	return text.remedy ? `${text.text} ${text.remedy}` : text.text;
}

/** The entry and the amount of the pair problem's remedy: split `difference` off the larger leg. */
export function differenceOf(problem: UnitProblem): number | null {
	if (problem.code !== 'pair_unequal') return null;
	const value = problem.detail.difference;
	return typeof value === 'number' && value !== 0 ? Math.abs(value) : null;
}

/** The split the server suggests for an unequal pair (the fee of a transfer), when it names one. */
export function suggestedSplitOf(problem: UnitProblem): SuggestedSplit | null {
	const found = problem.suggested_split;
	if (problem.code !== 'pair_unequal' || !found || found.amount.amount === 0) return null;
	return { source_entry_id: found.source_entry_id, amount: Math.abs(found.amount.amount) };
}
