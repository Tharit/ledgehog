import { describe, it, expect } from 'vitest';
import {
	amountHeader,
	columnCurrency,
	formatMoney,
	minorUnitDigits,
	parseMoneyInput
} from './money.js';

describe('minorUnitDigits', () => {
	it('follows the currency, not an assumption of two', () => {
		expect(minorUnitDigits('EUR')).toBe(2);
		expect(minorUnitDigits('JPY')).toBe(0);
		expect(minorUnitDigits('KWD')).toBe(3);
	});
});

describe('formatMoney', () => {
	it('formats English and German conventions', () => {
		expect(formatMoney(123456, 'EUR', { locale: 'en' })).toBe('+1,234.56');
		expect(formatMoney(123456, 'EUR', { locale: 'de' })).toBe('+1.234,56');
	});

	it('writes a true minus sign for negative amounts', () => {
		expect(formatMoney(-8431, 'EUR')).toBe('\u221284.31');
		expect(formatMoney(-8431, 'EUR')).not.toContain('-');
	});

	it('shows plus for positive amounts and nothing for zero', () => {
		expect(formatMoney(8000, 'EUR')).toBe('+80.00');
		expect(formatMoney(0, 'EUR')).toBe('0.00');
		expect(formatMoney(8000, 'EUR', { showPlus: false })).toBe('80.00');
	});

	it('pads the fraction and keeps small amounts exact', () => {
		expect(formatMoney(5, 'EUR')).toBe('+0.05');
		expect(formatMoney(-5, 'EUR')).toBe('\u22120.05');
		expect(formatMoney(100, 'EUR', { showPlus: false })).toBe('1.00');
	});

	it('uses the currency exponent', () => {
		expect(formatMoney(1500, 'JPY')).toBe('+1,500');
		expect(formatMoney(-1234567, 'KWD')).toBe('\u22121,234.567');
		expect(formatMoney(1234567, 'KWD', { locale: 'de' })).toBe('+1.234,567');
	});

	it('is exact beyond what a float holds', () => {
		expect(formatMoney(Number.MAX_SAFE_INTEGER, 'EUR', { showPlus: false })).toBe(
			'90,071,992,547,409.91'
		);
		expect(formatMoney(-Number.MAX_SAFE_INTEGER, 'JPY')).toBe('\u22129,007,199,254,740,991');
	});

	it('appends the currency code when asked', () => {
		expect(formatMoney(-5000, 'USD', { showCurrency: true })).toBe('\u221250.00\u00a0USD');
	});

	it('refuses a non-integer amount', () => {
		expect(() => formatMoney(1.5, 'EUR')).toThrow(RangeError);
		expect(() => formatMoney(NaN, 'EUR')).toThrow(RangeError);
	});
});

describe('parseMoneyInput', () => {
	const ok = (minor: number) => ({ ok: true, minor });
	const fail = (error: string) => ({ ok: false, error });

	it('parses English input', () => {
		expect(parseMoneyInput('1,234.56', 'EUR', 'en')).toEqual(ok(123456));
		expect(parseMoneyInput('1234.5', 'EUR', 'en')).toEqual(ok(123450));
		expect(parseMoneyInput('1234', 'EUR', 'en')).toEqual(ok(123400));
		expect(parseMoneyInput('.5', 'EUR', 'en')).toEqual(ok(50));
		expect(parseMoneyInput('1,234,567.89', 'EUR', 'en')).toEqual(ok(123456789));
	});

	it('parses German input', () => {
		expect(parseMoneyInput('1.234,56', 'EUR', 'de')).toEqual(ok(123456));
		expect(parseMoneyInput('1234,5', 'EUR', 'de')).toEqual(ok(123450));
		expect(parseMoneyInput(',5', 'EUR', 'de')).toEqual(ok(50));
		expect(parseMoneyInput('1.234.567,89', 'EUR', 'de')).toEqual(ok(123456789));
	});

	it('accepts spaces and apostrophes as groups', () => {
		expect(parseMoneyInput('1 234,56', 'EUR', 'de')).toEqual(ok(123456));
		expect(parseMoneyInput('1\u00a0234,56', 'EUR', 'de')).toEqual(ok(123456));
		expect(parseMoneyInput("1'234.56", 'EUR', 'en')).toEqual(ok(123456));
		expect(parseMoneyInput('1 234', 'EUR', 'en')).toEqual(ok(123400));
	});

	it('rejects a lone separator that could be a group or a decimal', () => {
		expect(parseMoneyInput('1,234', 'EUR', 'en')).toEqual(fail('ambiguous'));
		expect(parseMoneyInput('1.234', 'EUR', 'de')).toEqual(fail('ambiguous'));
		expect(parseMoneyInput('1,234', 'KWD', 'en')).toEqual(fail('ambiguous'));
		expect(parseMoneyInput('1,234', 'KWD', 'de')).toEqual(ok(1234));
	});

	it("rejects the other locale's separators instead of guessing", () => {
		expect(parseMoneyInput('1.5', 'EUR', 'de')).toEqual(fail('invalid'));
		expect(parseMoneyInput('1,5', 'EUR', 'en')).toEqual(fail('invalid'));
		expect(parseMoneyInput('1,234.56', 'EUR', 'de')).toEqual(fail('invalid'));
		expect(parseMoneyInput('1.234,56', 'EUR', 'en')).toEqual(fail('invalid'));
	});

	it('rejects malformed grouping and stray characters', () => {
		expect(parseMoneyInput('12,34,567.00', 'EUR', 'en')).toEqual(fail('invalid'));
		expect(parseMoneyInput('12 34', 'EUR', 'en')).toEqual(fail('invalid'));
		expect(parseMoneyInput('1.2.3', 'EUR', 'en')).toEqual(fail('invalid'));
		expect(parseMoneyInput('12.', 'EUR', 'en')).toEqual(fail('invalid'));
		expect(parseMoneyInput('.', 'EUR', 'en')).toEqual(fail('invalid'));
		expect(parseMoneyInput('abc', 'EUR', 'en')).toEqual(fail('invalid'));
		expect(parseMoneyInput('12 EUR', 'EUR', 'en')).toEqual(fail('invalid'));
	});

	it('rejects empty input', () => {
		expect(parseMoneyInput('', 'EUR')).toEqual(fail('empty'));
		expect(parseMoneyInput('   ', 'EUR')).toEqual(fail('empty'));
	});

	it('rejects more decimals than the currency has', () => {
		expect(parseMoneyInput('1.234', 'EUR', 'en')).toEqual(fail('too_many_decimals'));
		expect(parseMoneyInput('10.5', 'JPY', 'en')).toEqual(fail('too_many_decimals'));
		expect(parseMoneyInput('1.2345', 'KWD', 'en')).toEqual(fail('too_many_decimals'));
		expect(parseMoneyInput('1.234', 'KWD', 'en')).toEqual(ok(1234));
		expect(parseMoneyInput('1500', 'JPY', 'en')).toEqual(ok(1500));
	});

	it('reads an optional sign, with a hyphen or a true minus', () => {
		expect(parseMoneyInput('-84.31', 'EUR', 'en')).toEqual(ok(-8431));
		expect(parseMoneyInput('\u221284,31', 'EUR', 'de')).toEqual(ok(-8431));
		expect(parseMoneyInput('+80.00', 'EUR', 'en')).toEqual(ok(8000));
		expect(parseMoneyInput('-0', 'EUR', 'en')).toEqual(ok(0));
	});

	it('refuses an amount a safe integer cannot hold', () => {
		expect(parseMoneyInput('90071992547409.91', 'EUR', 'en')).toEqual(ok(Number.MAX_SAFE_INTEGER));
		expect(parseMoneyInput('90071992547409.92', 'EUR', 'en')).toEqual(fail('too_large'));
	});

	it('round-trips what it formats', () => {
		for (const minor of [0, 5, 100, 123456, 99999999]) {
			const text = formatMoney(minor, 'EUR', { locale: 'de', showPlus: false });
			expect(parseMoneyInput(text, 'EUR', 'de')).toEqual(ok(minor));
		}
	});
});

describe('columnCurrency / amountHeader', () => {
	it('names the one shared currency, else null', () => {
		expect(columnCurrency(['EUR', 'EUR'])).toBe('EUR');
		expect(columnCurrency(['EUR', 'USD'])).toBeNull();
		expect(columnCurrency([])).toBeNull();
	});
	it('puts the currency in the header', () => {
		expect(amountHeader('Amount', 'EUR')).toBe('Amount (EUR)');
		expect(amountHeader('Amount', null)).toBe('Amount');
	});
});
