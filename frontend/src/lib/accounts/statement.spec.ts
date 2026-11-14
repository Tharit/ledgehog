import { describe, expect, it } from 'vitest';
import { recordRow, sourceRow } from './fixtures.js';
import {
	cursorAfterRefetch,
	duplicateLabel,
	isInvestment,
	itemKey,
	lateArrivalsLabel,
	lateForLabel,
	recordGap,
	recordKindLabel
} from './statement.js';

describe('recordGap', () => {
	const eur = (amount: number) => ({ amount, currency: 'EUR' });

	it('states the expected balance and the difference', () => {
		const text = recordGap(recordRow({ balance: eur(100000), difference: eur(-350) }), {
			investment: false,
			locale: 'en'
		});
		expect(text).toBe('expected 1,003.50 · difference −3.50');
	});

	it('calls the difference a valuation on an investment account', () => {
		const text = recordGap(recordRow({ balance: eur(100000), difference: eur(2000) }), {
			investment: true,
			locale: 'en'
		});
		expect(text).toBe('expected 980.00 · valuation +20.00');
	});

	it('says nothing for a record the ledger explains', () => {
		expect(recordGap(recordRow(), { investment: false, locale: 'en' })).toBeNull();
	});

	it('says the opening for the anchor, zero included', () => {
		const anchor = (amount: number) => recordRow({ anchor: true, difference: eur(amount) });
		expect(recordGap(anchor(100000), { investment: false, locale: 'en' })).toBe('opening 1,000.00');
		expect(recordGap(anchor(0), { investment: true, locale: 'en' })).toBe('opening 0.00');
	});
});

describe('lateArrivalsLabel', () => {
	it('counts the bookings, singular for one, nothing for none', () => {
		expect(lateArrivalsLabel({ late_arrivals: 0 })).toBeNull();
		expect(lateArrivalsLabel({ late_arrivals: 1 })).toBe(
			'1 booking dated earlier arrived after this balance'
		);
		expect(lateArrivalsLabel({ late_arrivals: 4 })).toBe(
			'4 bookings dated earlier arrived after this balance'
		);
	});
});

describe('lateForLabel', () => {
	it('names the latest record the row is late for, nothing where it is not late', () => {
		expect(lateForLabel({ late_for: null })).toBeNull();
		expect(lateForLabel({ late_for: '2026-04-02' })).toBe('Arrived after the Apr 2, 2026 balance');
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
