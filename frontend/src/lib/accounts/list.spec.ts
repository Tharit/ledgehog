import { describe, expect, it } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import { orderAccounts } from './list.js';

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
