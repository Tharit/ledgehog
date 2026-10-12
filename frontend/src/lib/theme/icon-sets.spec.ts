import { describe, expect, it } from 'vitest';
import { CATEGORY_ICONS, PAYEE_ICONS } from './icon-sets.js';
import { isKnownIcon } from './icons.js';

describe('icon sets', () => {
	it('offer only icons the app can draw, once each', () => {
		for (const set of [CATEGORY_ICONS, PAYEE_ICONS]) {
			expect(set.filter((name) => !isKnownIcon(name))).toEqual([]);
			expect(new Set(set).size).toBe(set.length);
		}
	});

	it('hold the design set sizes', () => {
		expect(CATEGORY_ICONS).toHaveLength(58);
		expect(PAYEE_ICONS).toHaveLength(32);
	});
});
