import { describe, expect, it } from 'vitest';
import { describeProblem, differenceOf, problemSentence } from './problems.js';
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
