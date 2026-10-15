import { describe, expect, it } from 'vitest';
import { isCalendarDate, MAX_PURPOSE, validateEntry, type FormValues } from './validate.js';

const ok: FormValues = {
	accountId: 4,
	currency: 'EUR',
	date: '2026-10-13',
	amountText: '\u221212.50',
	purpose: '  groceries at REWE '
};

describe('validateEntry', () => {
	it('turns good values into the request fields: signed amount, trimmed purpose', () => {
		const { errors, input } = validateEntry(ok);

		expect(errors).toEqual({});
		expect(input).toEqual({
			account_id: 4,
			amount: -1250,
			booked_on: '2026-10-13',
			purpose: 'groceries at REWE'
		});
	});

	it('sends no purpose when it is blank', () => {
		expect(validateEntry({ ...ok, purpose: '   ' }).input?.purpose).toBeNull();
	});

	it('says what is wrong under which field', () => {
		const { errors, input } = validateEntry({
			...ok,
			accountId: null,
			currency: null,
			date: '',
			amountText: ''
		});

		expect(input).toBeNull();
		expect(errors).toEqual({
			account: 'Choose an account.',
			date: 'Enter a date.',
			amount: 'Enter an amount.'
		});
	});

	it('reads the amount in the account currency and refuses what it cannot read', () => {
		expect(validateEntry({ ...ok, currency: 'JPY', amountText: '-1.5' }).errors.amount).toBe(
			'JPY has no decimals.'
		);
		expect(validateEntry({ ...ok, amountText: '-1,234' }).errors.amount).toMatch(/two ways/);
	});

	it('sends money in as a positive amount and refuses a missing sign', () => {
		expect(validateEntry({ ...ok, amountText: '+12.50' }).input?.amount).toBe(1250);
		expect(validateEntry({ ...ok, amountText: '12.50' }).errors.amount).toBe(
			'Add a sign: \u2212 for money out, + for money in'
		);
	});

	it('limits the purpose to the server limit', () => {
		const long = 'x'.repeat(MAX_PURPOSE + 1);
		expect(validateEntry({ ...ok, purpose: long }).errors.purpose).toBe(
			`At most ${MAX_PURPOSE} characters.`
		);
		expect(validateEntry({ ...ok, purpose: 'x'.repeat(MAX_PURPOSE) }).errors).toEqual({});
	});
});

describe('isCalendarDate', () => {
	it('accepts real dates only', () => {
		expect(isCalendarDate('2026-02-28')).toBe(true);
		expect(isCalendarDate('2026-02-30')).toBe(false);
		expect(isCalendarDate('2026-13-01')).toBe(false);
		expect(isCalendarDate('')).toBe(false);
		expect(isCalendarDate('13.10.2026')).toBe(false);
	});
});
