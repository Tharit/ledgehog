import { describe, expect, it } from 'vitest';
import { cutFromSearchParams, withCut } from './queue-cut.js';

describe('the queue cut in the address', () => {
	it('is by counterparty unless the address says date (D275)', () => {
		expect(cutFromSearchParams('')).toBe('counterparty');
		expect(cutFromSearchParams('cut=date')).toBe('date');
		expect(cutFromSearchParams('cut=nonsense')).toBe('counterparty');
	});

	it('still reads the old ?cut=counterparty links as by counterparty', () => {
		expect(cutFromSearchParams('cut=counterparty')).toBe('counterparty');
		expect(cutFromSearchParams('account_id=2&cut=counterparty')).toBe('counterparty');
	});

	it('round-trips, keeps other parameters, and leaves "by counterparty" out', () => {
		const params = new URLSearchParams('account_id=2&unit=5');
		expect(withCut(params, 'date').toString()).toBe('account_id=2&unit=5&cut=date');
		expect(cutFromSearchParams(params)).toBe('date');
		expect(withCut(params, 'counterparty').toString()).toBe('account_id=2&unit=5');
		expect(cutFromSearchParams(params)).toBe('counterparty');
		expect(withCut(new URLSearchParams('cut=counterparty'), 'counterparty').toString()).toBe('');
	});
});
