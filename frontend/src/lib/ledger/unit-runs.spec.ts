import { describe, expect, it } from 'vitest';
import { entry } from './fixtures.js';
import { unitRuns, unitTotal } from './unit-runs.js';

describe('unitRuns', () => {
	it('groups adjacent entries of one unit_key; null keys and gaps never join', () => {
		const runs = unitRuns([
			entry({ id: 1, unit_key: 5 }),
			entry({ id: 2, unit_key: 5 }),
			entry({ id: 3, unit_key: null }),
			entry({ id: 4, unit_key: null }),
			entry({ id: 5, unit_key: 5 })
		]);
		expect(runs.map((r) => r.entries.map((e) => e.id))).toEqual([[1, 2], [3], [4], [5]]);
	});

	it('totals a split, not a pair, not mixed currencies', () => {
		const a = entry({ id: 1, amount: { amount: -300, currency: 'EUR' } });
		const b = entry({ id: 2, amount: { amount: -200, currency: 'EUR' } });
		expect(unitTotal([a, b])).toEqual({ amount: -500, currency: 'EUR' });
		expect(unitTotal([a])).toBeNull();
		expect(unitTotal([{ ...a, type: 'transfer' }, b])).toBeNull();
		expect(unitTotal([a, { ...b, amount: { amount: 1, currency: 'USD' } }])).toBeNull();
	});
});
