import { describe, expect, it } from 'vitest';
import { formatCount, formatRate } from './numbers.js';

describe('formatRate', () => {
	it('writes whole percent', () => {
		expect(formatRate(6349)).toBe('63%');
		expect(formatRate(-1260)).toBe('-13%');
		expect(formatRate(0)).toBe('0%');
	});

	it('writes a dash when there is no rate', () => {
		expect(formatRate(null)).toBe('—');
	});
});

describe('formatCount', () => {
	it('groups digits the way the locale does', () => {
		expect(formatCount(8000, 'en')).toBe('8,000');
		expect(formatCount(8000, 'de')).toBe('8.000');
		expect(formatCount(42)).toBe('42');
		expect(formatCount(0)).toBe('0');
	});
});
