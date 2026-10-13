// The entry form's amount: an unsigned text plus a sign choice become one signed integer of minor
// units in the ledger's sign convention (spec §3.9, patterns §2, architecture §6.6). Parsing is the
// locale's (`parseMoneyInput`); what it cannot read without guessing is refused with a message.
import { formatMoney, minorUnitDigits, parseMoneyInput } from '#lib/format/index.js';

export type Sign = 'expense' | 'income';

/** Spec §3.9: a hand-entered row is prefilled as an expense. */
export const DEFAULT_SIGN: Sign = 'expense';

export type AmountResult = { ok: true; minor: number } | { ok: false; message: string };

/** The sign of a stored amount: positive increases the account's balance (spec §3.3). */
export function signOf(minor: number): Sign {
	return minor < 0 ? 'expense' : 'income';
}

/** The magnitude as typed in the field: no group separators, so it reads back unambiguously. */
export function amountText(minor: number, currency: string, locale = 'en'): string {
	const magnitude = Math.abs(minor);
	const digits = minorUnitDigits(currency);
	if (digits === 0) return String(magnitude);
	const text = formatMoney(magnitude, currency, { locale, showPlus: false });
	const whole = text.slice(0, -(digits + 1)).replace(/\D/g, '');
	return whole + text.slice(-(digits + 1));
}

/** `12.50` and Expense in EUR are −1250; zero, a typed sign and anything ambiguous are refused. */
export function signedAmount(
	text: string,
	sign: Sign,
	currency: string,
	locale = 'en'
): AmountResult {
	if (/^\s*[-−+]/.test(text)) {
		return {
			ok: false,
			message: 'Enter the amount without a sign; choose Expense or Income instead.'
		};
	}
	const parsed = parseMoneyInput(text, currency, locale);
	if (!parsed.ok) {
		switch (parsed.error) {
			case 'empty':
				return { ok: false, message: 'Enter an amount.' };
			case 'ambiguous':
				return {
					ok: false,
					message: 'This could be read two ways. Write the amount with its decimals.'
				};
			case 'too_many_decimals': {
				const digits = minorUnitDigits(currency);
				return {
					ok: false,
					message:
						digits === 0
							? `${currency} has no decimals.`
							: `${currency} has ${digits} decimal${digits === 1 ? '' : 's'} at most.`
				};
			}
			case 'too_large':
				return { ok: false, message: 'This amount is too large.' };
			default:
				return { ok: false, message: 'This is not an amount.' };
		}
	}
	if (parsed.minor === 0) return { ok: false, message: 'An amount is never zero.' };
	return { ok: true, minor: sign === 'expense' ? -parsed.minor : parsed.minor };
}
