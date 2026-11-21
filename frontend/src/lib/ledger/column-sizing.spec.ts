import { describe, expect, it } from 'vitest';
import { sizeColumns, trackTemplate, type SizingColumn } from './column-sizing.js';

const cols = (measured: Record<string, number>): SizingColumn[] => [
	{ id: 'account', kind: 'flex', measured: measured.account, floor: 72, cap: 224 },
	{ id: 'payee', kind: 'flex', measured: measured.payee, floor: 72, cap: 256 },
	{ id: 'description', kind: 'fill', measured: measured.description, floor: 128, cap: 640 },
	{ id: 'amount', kind: 'fixed', width: 112 }
];

describe('sizeColumns', () => {
	it('gives each column its content and the rest to the fill column', () => {
		const w = sizeColumns(1000, cols({ account: 150, payee: 200, description: 300 }));
		expect(w).toEqual([150, 200, 538, 112]);
	});

	it('caps a column at its cap', () => {
		const w = sizeColumns(1000, cols({ account: 900, payee: 900, description: 100 }));
		expect(w.slice(0, 2)).toEqual([224, 256]);
	});

	it('shrinks the widest column first and keeps short ones complete', () => {
		// desired 100 / 200 / 640 into 600 - 112 = 488: ceiling 144 for payee and description
		const w = sizeColumns(600, cols({ account: 100, payee: 200, description: 640 }));
		expect(w[0]).toBe(100);
		expect(w[3]).toBe(112);
		expect(w[0] + w[1] + w[2]).toBeCloseTo(488);
		expect(w[1]).toBeCloseTo(w[2]);
		expect(w[1]).toBeCloseTo(194);
	});

	it('stops a column at its floor, then the next widest shrinks', () => {
		const w = sizeColumns(560, [
			{ id: 'a', kind: 'flex', measured: 200, floor: 100 },
			{ id: 'b', kind: 'flex', measured: 400, floor: 300 },
			{ id: 'c', kind: 'fill', measured: 150, floor: 50 }
		]);
		expect(w[1]).toBeCloseTo(300);
		expect(w[0]).toBeCloseTo(130);
		expect(w[2]).toBeCloseTo(130);
	});

	it('sums exactly to the room', () => {
		const w = sizeColumns(777, cols({ account: 210, payee: 250, description: 900 }));
		expect(w.reduce((a, b) => a + b, 0)).toBeCloseTo(777);
	});

	it('uses the floors when even those do not fit', () => {
		expect(sizeColumns(100, cols({ account: 150, payee: 200, description: 400 }))).toEqual([
			72, 72, 128, 112
		]);
	});

	it('never goes below the content when it is smaller than the floor', () => {
		expect(
			sizeColumns(1000, cols({ account: 30, payee: 40, description: 50 })).slice(0, 2)
		).toEqual([30, 40]);
	});
});

describe('trackTemplate', () => {
	it('lets the fill column grow when everything fits', () => {
		expect(trackTemplate(1000, cols({ account: 150, payee: 200, description: 300 }))).toBe(
			'150px 200px minmax(538px, 1fr) 112px'
		);
	});

	it('is all px when the widest give way, the fill column taking the rounding leftover', () => {
		const template = trackTemplate(488 + 112, cols({ account: 100, payee: 200, description: 640 }));
		expect(template).not.toContain('minmax');
		const px = template.split(' ').map((t) => parseInt(t, 10));
		expect(px.reduce((a, b) => a + b, 0)).toBe(600);
	});
});
