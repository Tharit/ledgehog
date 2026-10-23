import { describe, expect, it } from 'vitest';
import { describeProblem, differenceOf, problemSentence, suggestedSplitOf } from './problems.js';
import { problem } from './fixtures.js';

const context = { currency: () => 'EUR', locale: 'en' };
const words = (code: string, over = {}) => describeProblem(problem(code, over), context);

describe('describeProblem', () => {
	it('says a residual of zero with the remedy of the spec', () => {
		expect(words('residual_zero')).toEqual({
			text: 'The split leaves nothing for the original entry.',
			remedy: 'Make the new amounts smaller, or remove one.'
		});
	});

	it('says a residual that changed sign as too much taken', () => {
		expect(words('residual_sign_flip').text).toBe(
			'The new amounts add up to more than the transaction.'
		);
	});

	it('names the currency a transfer needs, from the numbers the server sent', () => {
		const text = words('currency_rule', { detail: { required: 'USD', actual: 'EUR' } });
		expect(text.text).toBe('This transfer needs an account in USD, not EUR.');
		expect(text.remedy).toBe('Choose an account in USD.');
	});

	it('writes the difference of an unequal pair as an amount, with the remedy of spec §5.7', () => {
		const text = words('pair_unequal', { detail: { partner: 2, difference: -1250 } });
		expect(text.text).toBe('The two legs of this transfer differ by 12.50.');
		expect(text.remedy).toBe(
			'Split the difference off the larger leg as a flow, or pick another partner.'
		);
	});

	it('writes amounts in the currency of the entry', () => {
		const usd = describeProblem(
			problem('split_sum', { entry_id: 7, detail: { difference: 500 } }),
			{
				locale: 'de',
				currency: (id) => (id === 7 ? 'USD' : 'EUR')
			}
		);
		expect(usd.text).toBe('The entries do not add up to the transaction: they are off by 5,00.');
	});

	it.each([
		['pair_sign', /opposite directions/],
		['second_transfer', /Only one entry of a transaction can be a transfer/],
		['new_entry_not_flow', /always a flow/],
		['own_counter_account', /its own account/],
		['amount_zero', /never for nothing/],
		['invariant_violated', /rule of the ledger/]
	])('says %s', (code, pattern) => {
		expect(words(code).text).toMatch(pattern);
	});

	it('tells a flow with an account from a transfer with a category', () => {
		expect(words('type_conflict', { field: 'counter_account' }).text).toBe(
			'A flow has no counter-account.'
		);
		expect(words('type_conflict', { field: 'category' }).text).toBe(
			'A transfer has no category or payee.'
		);
	});

	it('says a document on a transfer, with its remedy', () => {
		expect(words('document_not_for_transfer')).toEqual({
			text: 'A transfer cannot carry a document.',
			remedy: 'Pick a flow, or remove the document.'
		});
	});

	it('says a transfer beside a document, with its remedy', () => {
		expect(words('document_with_transfer')).toEqual({
			text: 'A transaction with a document cannot also have a transfer.',
			remedy: 'Keep every entry a flow, or remove the document.'
		});
	});

	it('names which pick vanished', () => {
		expect(words('stale_reference', { field: 'category_id' }).text).toMatch(/category/);
		expect(words('stale_reference', { field: 'payee_id' }).text).toMatch(/payee/);
		expect(words('stale_reference', { field: 'counter_account_id' }).text).toMatch(/account/);
	});

	it('does not echo a code it does not know', () => {
		expect(words('brand_new').text).toBe('This change cannot be committed.');
	});
});

describe('problemSentence and differenceOf', () => {
	it('joins the problem and its remedy', () => {
		expect(problemSentence({ text: 'A.', remedy: 'B.' })).toBe('A. B.');
		expect(problemSentence({ text: 'A.' })).toBe('A.');
	});

	it('reads the difference of an unequal pair as a magnitude, and of nothing else', () => {
		expect(differenceOf(problem('pair_unequal', { detail: { difference: -100 } }))).toBe(100);
		expect(differenceOf(problem('pair_unequal', { detail: { difference: 0 } }))).toBeNull();
		expect(differenceOf(problem('split_sum', { detail: { difference: 5 } }))).toBeNull();
	});
});

describe('the partner problems', () => {
	it('says a partner that is not offered, with the hint to widen the window while it is not widened', () => {
		const text = describeProblem(problem('partner_not_offered'), context);
		expect(text.text).toBe(
			'This entry is not offered as a partner (wrong account, direction or date).'
		);
		expect(text.remedy).toContain('load more candidates');
		const widened = describeProblem(problem('partner_not_offered'), { ...context, windowDays: 30 });
		expect(widened.remedy).toBe('Pick another partner.');
	});

	it('says a partner that is already in the unit', () => {
		expect(words('partner_in_unit').text).toBe('This entry is already part of this unit.');
	});
});

describe('suggestedSplitOf', () => {
	const money = (amount: number) => ({ amount, currency: 'EUR' });

	it('reads the suggestion of an unequal pair as a magnitude', () => {
		expect(
			suggestedSplitOf(
				problem('pair_unequal', { suggested_split: { source_entry_id: 4, amount: money(-250) } })
			)
		).toEqual({ source_entry_id: 4, amount: 250 });
	});

	it('is null without one, for another problem, and for nothing to split', () => {
		expect(suggestedSplitOf(problem('pair_unequal'))).toBeNull();
		expect(
			suggestedSplitOf(
				problem('pair_sign', { suggested_split: { source_entry_id: 1, amount: money(5) } })
			)
		).toBeNull();
		expect(
			suggestedSplitOf(
				problem('pair_unequal', { suggested_split: { source_entry_id: 1, amount: money(0) } })
			)
		).toBeNull();
	});
});

describe('the counter-leg problems', () => {
	it('names the currency of the amount received: from the detail, else from the counter-account', () => {
		expect(words('received_amount_required', { detail: { currency: 'USD' } }).text).toBe(
			'Enter the amount received in USD.'
		);
		const viaAccount = describeProblem(problem('received_amount_required', { entry_id: 1 }), {
			...context,
			counterCurrency: () => 'USD'
		});
		expect(viaAccount.text).toBe('Enter the amount received in USD.');
		expect(words('received_amount_required').text).toBe('Enter the amount received.');
	});

	it.each([
		['received_amount_not_needed', 'No amount is needed: both sides are in the same currency.'],
		[
			'counter_leg_not_offered',
			'The other side cannot be created here: this leg already has a partner, or the counter-account is unknown.'
		],
		[
			'counter_leg_account_synced',
			'The other side cannot be created by hand on a synced account: it arrives with its import.'
		]
	])('words %s', (code, text) => {
		expect(words(code).text).toBe(text);
	});
});

describe('the problems of a document', () => {
	it('asks for a decision, and says how to take it', () => {
		const text = words('document_decision_required', { entry_id: 1, field: 'document' });
		expect(text.text).toBe('A document is suggested or expected for this transaction.');
		expect(text.remedy).toBe('Pick one, or commit without a document.');
	});

	it('says a picked document changed, or was taken, with the remedy', () => {
		expect(words('document_changed')).toEqual({
			text: 'The document you picked has changed since you saw it.',
			remedy: 'Pick it again.'
		});
		expect(words('document_taken')).toEqual({
			text: 'The document you picked is carried by another transaction.',
			remedy: 'Pick another document.'
		});
	});

	it('says a document of another provider than the payee’s cannot be used', () => {
		const text = words('document_provider_mismatch');
		expect(text.text).toMatch(/another provider/);
		expect(text.remedy).toMatch(/payee provider/);
	});

	it('says a split that cannot be made, with the remedy', () => {
		const text = words('document_split_unavailable');
		expect(text.text).toMatch(/cannot split the transaction/);
		expect(text.remedy).toBe('Keep one entry, or pick another document.');
	});

	it('says a document that is gone like the other stale choices', () => {
		expect(words('stale_reference', { field: 'document_id' })).toEqual({
			text: 'The document you chose no longer exists.',
			remedy: 'Choose again.'
		});
	});
});
