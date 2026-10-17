import { describe, expect, it } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import { describeFacts } from './facts.js';

const ctx = { locale: 'en', today: '2026-10-17' };

describe('describeFacts', () => {
	it('says the data age relative to today with the date as title', () => {
		const [age] = describeFacts(account({ last_data_on: '2026-10-14' }), ctx);
		expect(age).toMatchObject({ id: 'age', text: 'Data from 3 days ago' });
		expect(age.title).toBe('Oct 14, 2026');
	});

	it('says never where there is no data', () => {
		expect(describeFacts(account({ last_data_on: null }), ctx)[0].text).toBe('Data: never');
	});

	it('says when the balance is not anchored', () => {
		const facts = describeFacts(account({ last_data_on: '2026-10-17', anchored: false }), ctx);
		expect(facts.map((f) => f.id)).toEqual(['age', 'anchor']);
		expect(facts[1].text).toBe('Balance not anchored');
	});

	it('says the unexplained difference as an amount, only when it is not zero', () => {
		const some = describeFacts(
			account({
				last_data_on: '2026-10-17',
				unexplained_difference: { amount: -1250, currency: 'EUR' }
			}),
			ctx
		);
		expect(some.at(-1)?.text).toBe('Unexplained difference −12.50');
		const none = describeFacts(
			account({
				last_data_on: '2026-10-17',
				unexplained_difference: { amount: 0, currency: 'EUR' }
			}),
			ctx
		);
		expect(none.map((f) => f.id)).toEqual(['age']);
	});
});
