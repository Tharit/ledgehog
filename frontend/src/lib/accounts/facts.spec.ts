import { describe, expect, it } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import { describeFacts, describePerformance } from './facts.js';

const ctx = { locale: 'en', today: '2026-10-17' };

describe('describeFacts', () => {
	it('says the data age relative to today with the date as title', () => {
		const [age] = describeFacts(account({ last_data_on: '2026-10-14' }), ctx);
		expect(age).toMatchObject({ id: 'age', text: 'Data from 3 days ago' });
		expect(age.title).toBe('Oct 14, 2026');
	});

	it('says "Valued" of an unsynced investment account and "Balance set" of another unsynced one', () => {
		const at = { last_data_on: '2026-10-14', synced: false };
		expect(describeFacts(account({ ...at, kind: 'depot' }), ctx)[0].text).toBe('Valued 3 days ago');
		expect(describeFacts(account({ ...at, kind: 'asset' }), ctx)[0].text).toBe('Valued 3 days ago');
		expect(describeFacts(account({ ...at, kind: 'checking' }), ctx)[0].text).toBe(
			'Balance set 3 days ago'
		);
		expect(
			describeFacts(account({ last_data_on: '2026-10-14', synced: true, kind: 'depot' }), ctx)[0]
				.text
		).toBe('Data from 3 days ago');
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

describe('describePerformance', () => {
	const invest = {
		net_deposits: { amount: 6_500_000, currency: 'EUR' },
		gain: { amount: 400_000, currency: 'EUR' },
		return_rate: 623,
		return_as_of: '2026-10-14'
	};

	it('says the gain, the return p.a. and the date', () => {
		const p = describePerformance(account(invest), { locale: 'en' });
		expect(p).toMatchObject({ gain: '+4,000.00\u00a0EUR', hasReturn: true, asOf: 'Oct 14, 2026' });
		expect(p?.return).toBe('+6.2\u00a0% p.a.');
		expect(p?.netDeposits).toBe('65,000.00\u00a0EUR');
	});

	it('says a dash for the return where there is none', () => {
		const p = describePerformance(account({ ...invest, return_rate: null }), { locale: 'en' });
		expect(p).toMatchObject({ return: '—', hasReturn: false });
	});

	it('is nothing on an account without the facts', () => {
		expect(describePerformance(account(), { locale: 'en' })).toBeNull();
	});
});
