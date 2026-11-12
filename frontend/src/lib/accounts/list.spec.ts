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
	const worth = (amount: number | null) => ({
		total: amount === null ? null : { amount, currency: 'EUR' },
		unvalued: amount === null ? [{ amount: { amount: 5, currency: 'USD' }, accounts: 1 }] : []
	});

	it('draws the server groups in its order, each with its open accounts in sort order, the closed last', () => {
		const groups = groupAccounts(
			[
				account({ id: 1, kind: 'cash', sort_order: 2 }),
				account({ id: 2, kind: 'checking' }),
				account({ id: 3, kind: 'cash', sort_order: 1 }),
				account({ id: 4, kind: 'checking', closed_on: '2026-01-01' })
			],
			[
				{ kind: 'checking', accounts: 1, net_worth: worth(1000) },
				{ kind: 'cash', accounts: 2, net_worth: worth(null) },
				{ kind: null, accounts: 1, net_worth: worth(0) }
			],
			'EUR'
		);
		expect(groups.map((g) => [g.key, g.label, g.accounts.map((a) => a.id)])).toEqual([
			['checking', 'Checking', [2]],
			['cash', 'Cash', [3, 1]],
			['closed', 'Closed', [4]]
		]);
		expect(groups[0].total).toMatchObject({ minor: 1000, currency: 'EUR' });
		expect(groups[1].total.minor).toBeNull(); // unvalued, not zero
	});
});
