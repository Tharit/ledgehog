import { describe, expect, it } from 'vitest';
import { amountText, DEFAULT_AMOUNT_TEXT, leadingSign, signChar, signedAmount } from './amount.js';

const NO_SIGN = 'Add a sign: \u2212 for money out, + for money in';

describe('the starting text', () => {
	it('is the minus alone: money out (spec §3.9)', () => {
		expect(DEFAULT_AMOUNT_TEXT).toBe('\u2212');
	});

	it('reads the sign of a stored amount and of typed text', () => {
		expect(signChar(-1)).toBe('\u2212');
		expect(signChar(1250)).toBe('+');
		expect(leadingSign('-3')).toBe('\u2212');
		expect(leadingSign(' \u22123')).toBe('\u2212');
		expect(leadingSign('+3')).toBe('+');
		expect(leadingSign('3')).toBeNull();
	});
});

describe('signedAmount', () => {
	it('reads +, \u2212 and - as the sign, in minor units', () => {
		expect(signedAmount('\u221212.50', 'EUR')).toEqual({ ok: true, minor: -1250 });
		expect(signedAmount('-12.50', 'EUR')).toEqual({ ok: true, minor: -1250 });
		expect(signedAmount('+12.50', 'EUR')).toEqual({ ok: true, minor: 1250 });
		expect(signedAmount('+1,234.50', 'EUR', 'en')).toEqual({ ok: true, minor: 123450 });
	});

	it('allows spaces around the sign and the amount', () => {
		expect(signedAmount('\u2212 12.50', 'EUR')).toEqual({ ok: true, minor: -1250 });
		expect(signedAmount('  + 12.50  ', 'EUR')).toEqual({ ok: true, minor: 1250 });
	});

	it('follows the locale and the currency', () => {
		expect(signedAmount('\u221212,5', 'EUR', 'de')).toEqual({ ok: true, minor: -1250 });
		expect(signedAmount('+1.234,50', 'EUR', 'de')).toEqual({ ok: true, minor: 123450 });
		expect(signedAmount('-500', 'JPY')).toEqual({ ok: true, minor: -500 });
	});

	it('requires a sign, with a message', () => {
		for (const text of ['12.50', ' 3', 'abc']) {
			expect(signedAmount(text, 'EUR')).toEqual({ ok: false, message: NO_SIGN });
		}
	});

	it('refuses an empty amount, or a sign alone', () => {
		for (const text of ['', '  ', '\u2212', '+', '- ']) {
			expect(signedAmount(text, 'EUR')).toEqual({ ok: false, message: 'Enter an amount.' });
		}
	});

	it('refuses zero in either sign', () => {
		for (const text of ['+0', '\u22120', '-0.00', '+0,00']) {
			expect(signedAmount(text, 'EUR', 'en')).toMatchObject({
				ok: false,
				message: expect.stringMatching(/never zero|not an amount/)
			});
		}
		expect(signedAmount('\u22120.00', 'EUR')).toEqual({
			ok: false,
			message: 'An amount is never zero.'
		});
	});

	it('refuses a doubled sign', () => {
		for (const text of ['\u2212\u22123', '+-3', '--3', '+ +3', '-+3']) {
			expect(signedAmount(text, 'EUR')).toEqual({ ok: false, message: 'Use one sign only.' });
		}
	});

	it('refuses an unreadable, ambiguous or too precise amount, with a message each', () => {
		const message = (text: string, currency = 'EUR') => {
			const result = signedAmount(text, currency);
			return result.ok ? null : result.message;
		};
		expect(message('\u22123abc')).toBe('This is not an amount.');
		expect(message('\u22121.234,5')).toBe('This is not an amount.');
		expect(message('\u221212.345')).toBe('EUR has 2 decimals at most.');
		expect(message('+1.5', 'JPY')).toBe('JPY has no decimals.');
		expect(message('-1,234')).toMatch(/two ways/);
	});
});

describe('amountText', () => {
	it('writes the signed amount with the locale decimal and no grouping, so it reads back', () => {
		expect(amountText(-123456, 'EUR', 'en')).toBe('\u22121234.56');
		expect(amountText(123456, 'EUR', 'de')).toBe('+1234,56');
		expect(amountText(-5, 'EUR', 'en')).toBe('\u22120.05');
		expect(amountText(-123400, 'JPY', 'en')).toBe('\u2212123400');
	});

	it.each([
		[-123456, 'EUR', 'en'],
		[7000, 'EUR', 'de'],
		[-100000000, 'EUR', 'en'],
		[1234, 'JPY', 'en']
	])('round-trips %s %s in %s', (minor, currency, locale) => {
		expect(signedAmount(amountText(minor, currency, locale), currency, locale)).toEqual({
			ok: true,
			minor
		});
	});
});
