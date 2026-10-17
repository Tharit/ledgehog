import { describe, expect, it } from 'vitest';
import { dayDistance, isNewer, originalCandidates } from './duplicate.js';
import { sourceRow } from './fixtures.js';

describe('originalCandidates', () => {
	const row = { id: 5, booked_on: '2026-10-10' };

	it('lists the nearest date first, ties by the later id, without the row itself', () => {
		const rows = [
			sourceRow({ id: 5, booked_on: '2026-10-10' }),
			sourceRow({ id: 1, booked_on: '2026-09-01' }),
			sourceRow({ id: 2, booked_on: '2026-10-12' }),
			sourceRow({ id: 3, booked_on: '2026-10-08' }),
			sourceRow({ id: 4, booked_on: '2026-10-11' })
		];
		expect(originalCandidates(row, rows).map((r) => r.id)).toEqual([4, 3, 2, 1]);
	});

	it('leaves out duplicates and rows entered by hand', () => {
		const rows = [
			sourceRow({
				id: 1,
				duplicate_of: { id: 9, booked_on: '2026-10-10', amount: { amount: -4000, currency: 'EUR' } }
			}),
			sourceRow({ id: 2, authored: true }),
			sourceRow({ id: 3 })
		];
		expect(originalCandidates(row, rows).map((r) => r.id)).toEqual([3]);
	});
});

describe('isNewer and dayDistance', () => {
	it('the later date is newer, then the later id', () => {
		expect(isNewer({ id: 1, booked_on: '2026-10-11' }, { id: 9, booked_on: '2026-10-10' })).toBe(
			true
		);
		expect(isNewer({ id: 1, booked_on: '2026-10-10' }, { id: 9, booked_on: '2026-10-10' })).toBe(
			false
		);
		expect(isNewer({ id: 9, booked_on: '2026-10-10' }, { id: 1, booked_on: '2026-10-10' })).toBe(
			true
		);
	});

	it('counts whole days across a month end', () => {
		expect(dayDistance('2026-10-01', '2026-09-29')).toBe(2);
	});
});
