// Money formatting and parsing (architecture §6.6, patterns §2). Amounts are signed integers in
// minor units; no float ever holds one. Locale conventions come from Intl, never from hand-written
// rules for one language.

const MINUS = '\u2212'; // a true minus sign, not a hyphen
const NBSP = '\u00a0';

export type MoneyFormatOptions = {
	locale?: string;
	/** Append the ISO code: needed where several currencies meet, or the amount is foreign. */
	showCurrency?: boolean;
	/** Write `+` before positive amounts (ledger convention shows the sign as stored). */
	showPlus?: boolean;
};

export type MoneyParseError = 'empty' | 'invalid' | 'ambiguous' | 'too_many_decimals' | 'too_large';

export type MoneyParseResult = { ok: true; minor: number } | { ok: false; error: MoneyParseError };

type Separators = { group: string; decimal: string };

const separatorCache = new Map<string, Separators>();

function separators(locale: string): Separators {
	let found = separatorCache.get(locale);
	if (!found) {
		const format = new Intl.NumberFormat(locale, { minimumFractionDigits: 1 });
		const parts = format.formatToParts(1234567.5);
		found = {
			group: parts.find((p) => p.type === 'group')?.value ?? ',',
			decimal: parts.find((p) => p.type === 'decimal')?.value ?? '.'
		};
		separatorCache.set(locale, found);
	}
	return found;
}

/** The number of minor-unit digits of a currency (JPY 0, EUR 2, KWD 3). */
export function minorUnitDigits(currency: string): number {
	const format = new Intl.NumberFormat('en', { style: 'currency', currency });
	return format.resolvedOptions().maximumFractionDigits as number;
}

export function formatMoney(
	minor: number,
	currency: string,
	{ locale = 'en', showCurrency = false, showPlus = true }: MoneyFormatOptions = {}
): string {
	if (!Number.isSafeInteger(minor)) throw new RangeError('an amount is an integer of minor units');
	const digits = minorUnitDigits(currency);
	const magnitude = BigInt(Math.abs(minor));
	const scale = 10n ** BigInt(digits);
	let text = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(magnitude / scale);
	if (digits > 0) {
		text += separators(locale).decimal + String(magnitude % scale).padStart(digits, '0');
	}
	const sign = minor < 0 ? MINUS : minor > 0 && showPlus ? '+' : '';
	return sign + text + (showCurrency ? NBSP + currency : '');
}

const SPACE_LIKE = /[\s\u2009\u202f'\u2019]/;

function escapeForClass(char: string): string {
	return char.replace(/[\\\]^-]/g, '\\$&');
}

/**
 * Parse what a user typed into minor units. Only the locale's decimal separator marks a decimal;
 * grouping must be well formed. A single separator that could be a thousands group or a decimal
 * ("1,234" in English) is rejected as ambiguous, never guessed.
 */
export function parseMoneyInput(text: string, currency: string, locale = 'en'): MoneyParseResult {
	let body = text.trim();
	if (body === '') return { ok: false, error: 'empty' };

	let negative = false;
	if (/^[-\u2212+]/.test(body)) {
		negative = body[0] !== '+';
		body = body.slice(1).trim();
	}
	if (!/^[\d.,\s\u2009\u202f'\u2019]+$/.test(body)) return { ok: false, error: 'invalid' };

	const { group, decimal } = separators(locale);
	const decimalAt = body.lastIndexOf(decimal);
	const integerText = decimalAt >= 0 ? body.slice(0, decimalAt) : body;
	const fraction = decimalAt >= 0 ? body.slice(decimalAt + 1) : '';
	if (!/^\d*$/.test(fraction) || (decimalAt >= 0 && fraction === '')) {
		return { ok: false, error: 'invalid' };
	}

	const hardGroup = SPACE_LIKE.test(group) ? '' : escapeForClass(group);
	const groupChars = new RegExp(`[\\s\\u2009\\u202f'\\u2019${hardGroup}]`);
	const groups = integerText.trim().split(groupChars);
	if (!groups.every((g) => /^\d*$/.test(g))) return { ok: false, error: 'invalid' };
	if (groups.length > 1) {
		const wellFormed =
			/^\d{1,3}$/.test(groups[0]) && groups.slice(1).every((g) => /^\d{3}$/.test(g));
		if (!wellFormed) return { ok: false, error: 'invalid' };
		// a lone '.' or ',' followed by three digits reads as a group or as a decimal
		const separator = integerText.trim()[groups[0].length];
		if (groups.length === 2 && decimalAt < 0 && !SPACE_LIKE.test(separator)) {
			return { ok: false, error: 'ambiguous' };
		}
	}
	const integerDigits = groups.join('');
	if (integerDigits === '' && fraction === '') return { ok: false, error: 'invalid' };

	const digits = minorUnitDigits(currency);
	if (fraction.length > digits) return { ok: false, error: 'too_many_decimals' };

	const whole = BigInt(integerDigits || '0') * 10n ** BigInt(digits);
	const minor = whole + BigInt(fraction.padEnd(digits, '0') || '0');
	if (minor > BigInt(Number.MAX_SAFE_INTEGER)) return { ok: false, error: 'too_large' };
	return { ok: true, minor: negative ? -Number(minor) || 0 : Number(minor) };
}
