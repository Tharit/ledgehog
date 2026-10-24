// The email importer's settings as a form (plugins/importers/email.md §1): plain strings; the server
// is the judge, the checks here only spare a round trip. `port` and `mailbox` are optional and left
// out of the settings when empty. The senders are one address per line.
import type { IsoDate } from '#lib/format/index.js';

export type EmailDraft = {
	host: string;
	security: 'tls' | 'starttls';
	port: string;
	username: string;
	mailbox: string;
	/** one address per line */
	senders: string;
	startDate: IsoDate | '';
};

export const EMAIL_FIELDS: readonly string[] = [
	'host',
	'security',
	'port',
	'username',
	'mailbox',
	'senders',
	'start_date'
];

export const DEFAULT_MAILBOX = 'INBOX';

/** On add: TLS, the INBOX, and the start date the catalog offers, else today. */
export function emptyDraft(context?: { startDate: IsoDate | null; today: IsoDate }): EmailDraft {
	return {
		host: '',
		security: 'tls',
		port: '',
		username: '',
		mailbox: DEFAULT_MAILBOX,
		senders: '',
		startDate: context ? (context.startDate ?? context.today) : ''
	};
}

const str = (v: unknown): string => (typeof v === 'string' ? v : '');

export function draftFromSettings(settings: Record<string, unknown>): EmailDraft {
	return {
		host: str(settings.host),
		security: settings.security === 'starttls' ? 'starttls' : 'tls',
		port: typeof settings.port === 'number' ? String(settings.port) : '',
		username: str(settings.username),
		mailbox: str(settings.mailbox) || DEFAULT_MAILBOX,
		senders: Array.isArray(settings.senders) ? settings.senders.map(str).join('\n') : '',
		startDate: str(settings.start_date)
	};
}

/** The addresses of the textarea: trimmed, lower-cased, empty lines dropped, repeats left out. */
export function sendersOf(text: string): string[] {
	const found = text
		.split('\n')
		.map((line) => line.trim().toLowerCase())
		.filter((line) => line !== '');
	return [...new Set(found)];
}

export function settingsFromDraft(d: EmailDraft): Record<string, unknown> {
	const settings: Record<string, unknown> = {
		host: d.host.trim(),
		security: d.security,
		username: d.username.trim(),
		senders: sendersOf(d.senders),
		start_date: d.startDate
	};
	const port = d.port.trim();
	if (port !== '' && /^\d+$/.test(port)) settings.port = Number(port);
	const mailbox = d.mailbox.trim();
	if (mailbox !== '') settings.mailbox = mailbox;
	return settings;
}

const ADDRESS = /^[^\s@<>,;:"()[\]\\]+@[^\s@<>,;:"()[\]\\]+$/;

/** The client's checks, by field id (the setting key); empty when the draft passes. */
export function problemsOf(d: EmailDraft): Record<string, string> {
	const found: Record<string, string> = {};
	const host = d.host.trim();
	if (host === '') found.host = 'Enter the mail server.';
	else if (/[\s/:@]/.test(host)) {
		found.host = 'Enter the server name only: no https://, port or address.';
	}
	const port = d.port.trim();
	if (port !== '' && (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535)) {
		found.port = 'The port is a whole number from 1 to 65535.';
	}
	if (d.username.trim() === '') found.username = 'Enter the login name.';
	const senders = sendersOf(d.senders);
	if (senders.length === 0) found.senders = 'Enter at least one sender address.';
	else if (senders.some((s) => !ADDRESS.test(s))) {
		found.senders = 'Every line must be one address, like name@example.com.';
	}
	if (d.startDate === '') found.start_date = 'Choose the start date.';
	return found;
}

/** The field a refused setting stands under, or null when the form has none for it. */
export function fieldOfSetting(setting: string): string | null {
	return EMAIL_FIELDS.includes(setting) ? setting : null;
}
