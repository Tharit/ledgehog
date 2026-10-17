// The entry form's amount: one text with a required leading sign becomes one signed integer of minor
// units in the ledger's sign convention (spec §3.9, patterns §2, architecture §6.6). Parsing is the
// locale's (`parseMoneyInput`); what it cannot read without guessing is refused with a message.
import {
	formatMoney,
	minorUnitDigits,
	parseMoneyInput,
	type MoneyParseError
} from '#lib/format/index.js';

/** The minus the field shows and prefills: U+2212, as `lib/format` displays it. */
export const MINUS = '\u2212';
export const PLUS = '+';
/** Under the field: what the sign means. */
export const AMOUNT_HINT = '\u2212 money out, + money in';
/** Spec §3.9: a hand-entered row starts as money out, so the field starts as the minus alone. */
export const DEFAULT_AMOUNT_TEXT = MINUS;

export type AmountResult = { ok: true; minor: number } | { ok: false; message: string };

/** The sign character of a stored amount: positive increases the account's balance (spec §3.3). */
export function signChar(minor: number): string {
	return minor < 0 ? MINUS : PLUS;
}

/** The leading sign of what was typed, '−' or '+' ('-' counts as '−'); null when there is none. */
export function leadingSign(text: string): string | null {
	const first = text.trimStart()[0];
	if (first === '+') return PLUS;
	if (first === '-' || first === MINUS) return MINUS;
	return null;
}

/** The signed value as typed in the field: sign and magnitude, no group separators, so it reads back. */
export function amountText(minor: number, currency: string, locale = 'en'): string {
	const magnitude = Math.abs(minor);
	const digits = minorUnitDigits(currency);
	if (digits === 0) return signChar(minor) + String(magnitude);
	const text = formatMoney(magnitude, currency, { locale, showPlus: false });
	const whole = text.slice(0, -(digits + 1)).replace(/\D/g, '');
	return signChar(minor) + whole + text.slice(-(digits + 1));
}

/** What a refused amount text says (the locale's parser refuses what it cannot read without guessing). */
export function describeParseError(error: MoneyParseError, currency: string): string {
	switch (error) {
		case 'empty':
			return 'Enter an amount.';
		case 'ambiguous':
			return 'This could be read two ways. Write the amount with its decimals.';
		case 'too_many_decimals': {
			const digits = minorUnitDigits(currency);
			return digits === 0
				? `${currency} has no decimals.`
				: `${currency} has ${digits} decimal${digits === 1 ? '' : 's'} at most.`;
		}
		case 'too_large':
			return 'This amount is too large.';
		default:
			return 'This is not an amount.';
	}
}

/**
 * `−12.50` in EUR is −1250 and `+12.50` is 1250. Exactly one leading sign ('+', '−' or '-', a space may
 * follow) is required; zero, a doubled sign and anything ambiguous are refused.
 */
export function signedAmount(text: string, currency: string, locale = 'en'): AmountResult {
	const trimmed = text.trim();
	if (trimmed === '') return { ok: false, message: 'Enter an amount.' };
	const sign = leadingSign(trimmed);
	if (sign === null)
		return { ok: false, message: 'Add a sign: \u2212 for money out, + for money in' };
	const body = trimmed.slice(1).trim();
	if (body === '') return { ok: false, message: 'Enter an amount.' };
	if (/^[-\u2212+]/.test(body)) return { ok: false, message: 'Use one sign only.' };
	const parsed = parseMoneyInput(body, currency, locale);
	if (!parsed.ok) return { ok: false, message: describeParseError(parsed.error, currency) };
	if (parsed.minor === 0) return { ok: false, message: 'An amount is never zero.' };
	return { ok: true, minor: sign === MINUS ? -parsed.minor : parsed.minor };
}
