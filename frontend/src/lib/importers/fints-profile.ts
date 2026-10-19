// The FinTS importer's settings as a form: four plain strings (the server's schema is the
// importer's own; the server is the judge, the checks here only spare a round trip). `customer_id`
// is optional and left out of the settings when empty.
export type FintsDraft = {
	url: string;
	bankCode: string;
	userId: string;
	customerId: string;
};

export const FINTS_FIELDS: readonly string[] = ['url', 'bank_code', 'user_id', 'customer_id'];

export function emptyDraft(): FintsDraft {
	return { url: '', bankCode: '', userId: '', customerId: '' };
}

const str = (v: unknown): string => (typeof v === 'string' ? v : '');

export function draftFromSettings(settings: Record<string, unknown>): FintsDraft {
	return {
		url: str(settings.url),
		bankCode: str(settings.bank_code),
		userId: str(settings.user_id),
		customerId: str(settings.customer_id)
	};
}

export function settingsFromDraft(d: FintsDraft): Record<string, unknown> {
	const settings: Record<string, unknown> = {
		url: d.url.trim(),
		bank_code: d.bankCode.trim(),
		user_id: d.userId.trim()
	};
	const customer = d.customerId.trim();
	if (customer !== '') settings.customer_id = customer;
	return settings;
}

/** The client's checks, by field id (the setting key); empty when the draft passes. */
export function problemsOf(d: FintsDraft): Record<string, string> {
	const found: Record<string, string> = {};
	const url = d.url.trim();
	if (url === '') found.url = 'Enter the bank address.';
	else if (!url.startsWith('https://')) found.url = 'The bank address must start with https://.';
	const code = d.bankCode.trim();
	if (code === '') found.bank_code = 'Enter the bank code.';
	else if (!/^\d{8}$/.test(code)) found.bank_code = 'The bank code is eight digits.';
	if (d.userId.trim() === '') found.user_id = 'Enter the login name.';
	return found;
}

/** The field a refused setting stands under, or null when the form has none for it. */
export function fieldOfSetting(setting: string): string | null {
	return FINTS_FIELDS.includes(setting) ? setting : null;
}
