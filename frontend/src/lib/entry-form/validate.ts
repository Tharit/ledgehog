// The entry form's values checked before anything is sent: what goes under which field.
import { signedAmount, type Sign } from './amount.js';

export const MAX_PURPOSE = 500;

export type FormValues = {
	accountId: number | null;
	/** the account's currency, when one is chosen */
	currency: string | null;
	date: string;
	amountText: string;
	sign: Sign;
	purpose: string;
};

export type FieldName = 'account' | 'date' | 'amount' | 'purpose';
export type FieldErrors = Partial<Record<FieldName, string>>;

export type EntryInput = {
	account_id: number;
	amount: number;
	booked_on: string;
	purpose: string | null;
};

export function isCalendarDate(text: string): boolean {
	const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
	if (!match) return false;
	const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
	const date = new Date(Date.UTC(year, month - 1, day));
	return date.getUTCMonth() === month - 1 && date.getUTCDate() === day && year >= 1900;
}

export function validateEntry(
	values: FormValues,
	locale = 'en'
): { errors: FieldErrors; input: null } | { errors: FieldErrors; input: EntryInput } {
	const errors: FieldErrors = {};
	if (values.accountId === null || values.currency === null) errors.account = 'Choose an account.';
	if (!isCalendarDate(values.date)) errors.date = 'Enter a date.';
	let minor = 0;
	if (values.currency !== null) {
		const amount = signedAmount(values.amountText, values.sign, values.currency, locale);
		if (amount.ok) minor = amount.minor;
		else errors.amount = amount.message;
	} else if (values.amountText.trim() === '') {
		errors.amount = 'Enter an amount.';
	}
	const purpose = values.purpose.trim();
	if (purpose.length > MAX_PURPOSE) {
		errors.purpose = `At most ${MAX_PURPOSE} characters.`;
	}
	if (Object.keys(errors).length > 0 || values.accountId === null) return { errors, input: null };
	return {
		errors,
		input: {
			account_id: values.accountId,
			amount: minor,
			booked_on: values.date,
			purpose: purpose === '' ? null : purpose
		}
	};
}
