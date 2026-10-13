import { describe, expect, it } from 'vitest';
import { amountText, DEFAULT_SIGN, signedAmount, signOf } from './amount.js';

describe('sign', () => {
	it('is prefilled as an expense (spec §3.9)', () => {
		expect(DEFAULT_SIGN).toBe('expense');
	});

	it('is read from a stored amount: negative is an expense, positive income', () => {
		expect(signOf(-1)).toBe('expense');
		expect(signOf(1250)).toBe('income');
	});
});

describe('signedAmount', () => {
	it('makes an expense negative and an income positive, in minor units', () => {
		expect(signedAmount('12.50', 'expense', 'EUR')).toEqual({ ok: true, minor: -1250 });
		expect(signedAmount('12.50', 'income', 'EUR')).toEqual({ ok: true, minor: 1250 });
		expect(signedAmount('1,234.50', 'income', 'EUR', 'en')).toEqual({ ok: true, minor: 123450 });
	});

	it('follows the locale and the currency', () => {
		expect(signedAmount('12,5', 'expense', 'EUR', 'de')).toEqual({ ok: true, minor: -1250 });
		expect(signedAmount('500', 'expense', 'JPY')).toEqual({ ok: true, minor: -500 });
	});

	it('refuses an empty, unreadable, zero or too precise amount, with a message each', () => {
		const message = (text: string, currency = 'EUR') => {
			const result = signedAmount(text, 'expense', currency);
			return result.ok ? null : result.message;
		};
		expect(message('')).toBe('Enter an amount.');
		expect(message('abc')).toBe('This is not an amount.');
		expect(message('0.00')).toBe('An amount is never zero.');
		expect(message('1.234,5')).toBe('This is not an amount.');
		expect(message('12.345')).toBe('EUR has 2 decimals at most.');
		expect(message('1.5', 'JPY')).toBe('JPY has no decimals.');
	});

	it('does not guess an ambiguous single separator', () => {
		const result = signedAmount('1,234', 'expense', 'EUR', 'en');
		expect(result.ok).toBe(false);
		expect(result.ok ? '' : result.message).toMatch(/two ways/);
	});

	it('takes the sign from the control only: a typed sign is refused', () => {
		for (const text of ['-12.50', '+12.50', '−12.50', ' -3']) {
			const result = signedAmount(text, 'expense', 'EUR');
			expect(result.ok).toBe(false);
			expect(result.ok ? '' : result.message).toMatch(/without a sign/);
		}
	});
});

describe('amountText', () => {
	it('writes the magnitude with the locale decimal and no grouping, so it reads back', () => {
		expect(amountText(-123456, 'EUR', 'en')).toBe('1234.56');
		expect(amountText(123456, 'EUR', 'de')).toBe('1234,56');
		expect(amountText(-5, 'EUR', 'en')).toBe('0.05');
		expect(amountText(-123400, 'JPY', 'en')).toBe('123400');
	});

	it.each([
		[-123456, 'EUR', 'en'],
		[7000, 'EUR', 'de'],
		[-100000000, 'EUR', 'en'],
		[1234, 'JPY', 'en']
	])('round-trips %s %s in %s', (minor, currency, locale) => {
		const result = signedAmount(
			amountText(minor, currency, locale),
			signOf(minor),
			currency,
			locale
		);
		expect(result).toEqual({ ok: true, minor });
	});
});
