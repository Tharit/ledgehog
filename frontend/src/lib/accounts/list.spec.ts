import { describe, expect, it } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import { groupAccounts, orderAccounts } from './list.js';

describe('orderAccounts', () => {
	it('puts open accounts first in their sort order, then the closed ones', () => {
		const ordered = orderAccounts([
			account({ id: 1, sort_order: 0, closed_on: '2026-01-01' }),
			account({ id: 2, sort_order: 5 }),
			account({ id: 3, sort_order: 1 }),
			account({ id: 4, sort_order: 0, closed_on: '2025-01-01' })
		]);
		expect(ordered.map((a) => a.id)).toEqual([3, 2, 1, 4]);
	});
});

describe('groupAccounts', () => {
	const eur = (amount: number) => ({ amount, currency: 'EUR' });

	it('draws the server groups in its order, each with its open accounts in sort order, the closed last', () => {
		const groups = groupAccounts(
			[
				account({ id: 1, kind: 'cash', sort_order: 2 }),
				account({ id: 2, kind: 'checking' }),
				account({ id: 3, kind: 'cash', sort_order: 1 }),
				account({ id: 4, kind: 'checking', closed_on: '2026-01-01' })
			],
			[
				{ kind: 'checking', accounts: 1, sums: [eur(1000)] },
				{ kind: 'cash', accounts: 2, sums: [eur(5), { amount: 7, currency: 'USD' }] },
				{ kind: null, accounts: 1, sums: [eur(0)] }
			]
		);
		expect(groups.map((g) => [g.key, g.label, g.accounts.map((a) => a.id)])).toEqual([
			['checking', 'Checking', [2]],
			['cash', 'Cash', [3, 1]],
			['closed', 'Closed', [4]]
		]);
		// the sums are the server's, one per currency, never converted
		expect(groups[0].sums).toEqual([eur(1000)]);
		expect(groups[1].sums).toHaveLength(2);
	});

	it('names the currency a group shares, none where mixed, and marks the investment groups', () => {
		const groups = groupAccounts(
			[
				account({ id: 1, kind: 'cash', balance: eur(1) }),
				account({ id: 2, kind: 'cash', balance: { amount: 2, currency: 'USD' } }),
				account({ id: 3, kind: 'depot', balance: eur(3) }),
				account({ id: 4, kind: 'asset', balance: eur(4) })
			],
			[
				{ kind: 'cash', accounts: 2, sums: [] },
				{ kind: 'depot', accounts: 1, sums: [] },
				{ kind: 'asset', accounts: 1, sums: [] }
			]
		);
		expect(groups.map((g) => [g.currency, g.investment])).toEqual([
			[null, false],
			['EUR', true],
			['EUR', true]
		]);
	});
});
