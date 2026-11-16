import { describe, expect, it } from 'vitest';
import { account, category, payee } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { targetOptions } from './targets.js';

describe('targetOptions', () => {
	const lookups = buildLookups({
		accounts: [
			account({ id: 1, name: 'Zeta' }),
			account({ id: 2, name: 'Alpha', closed_on: '2025-01-01' }),
			account({ id: 3, name: 'Beta' }),
			account({ id: 4, name: 'Aardvark', closed_on: '2099-01-01' })
		],
		categories: [category({ id: 10, name: 'Rent' }), category({ id: 11, name: 'Food' })],
		payees: [payee({ id: 20, name: 'REWE' }), payee({ id: 21, name: 'Aldi' })]
	});

	it('lists every account, the open ones first and the closed ones after, each by name', () => {
		expect(targetOptions('counter_account', lookups).map((o) => o.label)).toEqual([
			'Beta',
			'Zeta',
			'Aardvark',
			'Alpha'
		]);
	});

	it('keeps categories and payees sorted by name', () => {
		expect(targetOptions('category', lookups).map((o) => o.label)).toEqual(['Food', 'Rent']);
		expect(targetOptions('payee', lookups).map((o) => o.label)).toEqual(['Aldi', 'REWE']);
	});
});
