import { describe, expect, it } from 'vitest';
import { formatCount } from './numbers.js';

describe('formatCount', () => {
	it('groups digits the way the locale does', () => {
		expect(formatCount(8000, 'en')).toBe('8,000');
		expect(formatCount(8000, 'de')).toBe('8.000');
		expect(formatCount(42)).toBe('42');
		expect(formatCount(0)).toBe('0');
	});
});
