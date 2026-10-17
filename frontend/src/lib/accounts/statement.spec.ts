import { describe, expect, it } from 'vitest';
import { recordRow, sourceRow } from './fixtures.js';
import {
	cursorAfterRefetch,
	duplicateLabel,
	isInvestment,
	itemKey,
	recordGap,
	recordKindLabel
} from './statement.js';

describe('recordGap', () => {
	it('says what the rows add up to and the difference', () => {
		const text = recordGap(
			recordRow({
				rows_sum: { amount: -5000, currency: 'EUR' },
				difference: { amount: -350, currency: 'EUR' }
			}),
			{ investment: false, locale: 'en' }
		);
		expect(text).toBe('rows add up to −50.00 · difference −3.50');
	});

	it('calls the difference a valuation on an investment account', () => {
		const text = recordGap(
			recordRow({
				rows_sum: { amount: 0, currency: 'EUR' },
				difference: { amount: 2000, currency: 'EUR' }
			}),
			{ investment: true, locale: 'en' }
		);
		expect(text).toBe('rows add up to 0.00 · valuation +20.00');
	});

	it('says nothing for the anchor or a record whose rows add up', () => {
		expect(
			recordGap(recordRow({ rows_sum: null, difference: null }), {
				investment: false,
				locale: 'en'
			})
		).toBeNull();
		expect(recordGap(recordRow(), { investment: false, locale: 'en' })).toBeNull();
	});
});

describe('labels and keys', () => {
	it('names the kind of a record', () => {
		expect(recordKindLabel({ record_kind: 'reported' })).toBe('Reported balance');
		expect(recordKindLabel({ record_kind: 'manual' })).toBe('Manual balance');
	});

	it('names the row a duplicate duplicates by date and amount', () => {
		const label = duplicateLabel(
			{ id: 3, booked_on: '2026-10-09', amount: { amount: -4000, currency: 'EUR' } },
			'en'
		);
		expect(label).toBe('duplicate of Oct 9, 2026 · −40.00');
	});

	it('keeps source and record ids apart', () => {
		expect(itemKey(sourceRow({ id: 4 }))).toBe('source:4');
		expect(itemKey(recordRow({ id: 4 }))).toBe('record:4');
	});

	it('knows the investment kinds', () => {
		expect(isInvestment('depot')).toBe(true);
		expect(isInvestment('asset')).toBe(true);
		expect(isInvestment('checking')).toBe(false);
	});
});

describe('cursorAfterRefetch', () => {
	const items = [sourceRow({ id: 3 }), sourceRow({ id: 2 }), sourceRow({ id: 1 })];

	it('keeps the row it was on', () => {
		expect(cursorAfterRefetch(items, 'source:2', 0)).toBe('source:2');
	});

	it('goes to the row now in its place when its row is gone', () => {
		expect(cursorAfterRefetch(items, 'source:9', 1)).toBe('source:2');
		expect(cursorAfterRefetch(items, 'source:9', 7)).toBe('source:1');
	});

	it('has none for no rows', () => {
		expect(cursorAfterRefetch([], 'source:9', 0)).toBeNull();
	});
});
