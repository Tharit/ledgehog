import { describe, expect, it } from 'vitest';
import { isKnownIcon } from './icons.js';
import { MEASURE_ICONS, measureLook, type Measure } from './measures.js';

describe('MEASURE_ICONS', () => {
	it('names an icon of the curated set for every measure', () => {
		for (const [measure, icon] of Object.entries(MEASURE_ICONS)) {
			expect(isKnownIcon(icon), `${measure} -> ${icon}`).toBe(true);
		}
	});

	it('knows the zero state of the review queue, which is not a measure of its own', () => {
		expect(isKnownIcon('check')).toBe(true);
	});
});

describe('measureLook', () => {
	it('is the measure’s fixed icon on stone', () => {
		expect(measureLook('net_worth')).toEqual({ icon: 'sigma', color: 'stone' });
		expect(measureLook('income')).toEqual({ icon: 'hand-coins', color: 'stone' });
	});

	it('is stone for every measure', () => {
		for (const measure of Object.keys(MEASURE_ICONS) as Measure[]) {
			expect(measureLook(measure).color).toBe('stone');
		}
	});
});
