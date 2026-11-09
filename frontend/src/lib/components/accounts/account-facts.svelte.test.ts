import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import AccountFacts from './account-facts.svelte';

const invest = {
	kind: 'investment' as const,
	net_deposits: { amount: 6_500_000, currency: 'EUR' },
	gain: { amount: 400_000, currency: 'EUR' },
	return_as_of: '2026-10-14'
};
const line = (over: Parameters<typeof account>[0]) => {
	const { container } = render(AccountFacts, {
		props: { account: account(over), today: '2026-10-18' }
	});
	return container.querySelector('[data-slot="performance-line"]');
};

describe('AccountFacts: the performance line', () => {
	it('adds the gain and the return p.a. under the balance', () => {
		expect(
			line({ ...invest, return_rate: 623 })
				?.textContent?.replace(/\s+/g, ' ')
				.trim()
		).toBe('gain +4,000.00 EUR · +6.2 % p.a.');
	});

	it('says the gain alone where there is no return yet', () => {
		expect(
			line({ ...invest, return_rate: null })
				?.textContent?.replace(/\s+/g, ' ')
				.trim()
		).toBe('gain +4,000.00 EUR');
	});

	it('adds nothing to a non-investment account', () => {
		expect(line({})).toBeNull();
	});
});
