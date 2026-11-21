import { describe, expect, it } from 'vitest';
import { cutFromSearchParams, withCut } from './queue-cut.js';

describe('the queue cut in the address', () => {
	it('is by date unless the address says counterparty', () => {
		expect(cutFromSearchParams('')).toBe('date');
		expect(cutFromSearchParams('cut=nonsense')).toBe('date');
		expect(cutFromSearchParams('cut=counterparty')).toBe('counterparty');
	});

	it('round-trips, keeps other parameters, and leaves "by date" out', () => {
		const params = new URLSearchParams('account_id=2&unit=5');
		expect(withCut(params, 'counterparty').toString()).toBe('account_id=2&unit=5&cut=counterparty');
		expect(cutFromSearchParams(params)).toBe('counterparty');
		expect(withCut(params, 'date').toString()).toBe('account_id=2&unit=5');
	});
});
