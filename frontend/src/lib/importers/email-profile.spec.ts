import { describe, expect, it } from 'vitest';
import {
	draftFromSettings,
	emptyDraft,
	fieldOfSetting,
	problemsOf,
	sendersOf,
	settingsFromDraft
} from './email-profile.js';
import { settingsFormOf } from './forms.js';

const filled = () => ({
	...emptyDraft({ startDate: null, today: '2026-10-24' }),
	host: 'imap.example.org',
	username: 'me',
	senders: 'Shop@Example.com\n\n  other@example.org  \nshop@example.com'
});

describe('the email form adapter', () => {
	it('is registered, and prefills TLS, INBOX and the catalog start date, else today', () => {
		expect(settingsFormOf('email')).not.toBeNull();
		expect(emptyDraft({ startDate: '2026-03-01', today: '2026-10-24' })).toMatchObject({
			security: 'tls',
			mailbox: 'INBOX',
			port: '',
			startDate: '2026-03-01'
		});
		expect(emptyDraft({ startDate: null, today: '2026-10-24' }).startDate).toBe('2026-10-24');
	});

	it('reads senders as lines: trimmed, lower-cased, empty lines and repeats dropped', () => {
		expect(sendersOf(filled().senders)).toEqual(['shop@example.com', 'other@example.org']);
	});

	it('leaves out an empty port, sends a set one as a number', () => {
		const empty = settingsFromDraft(filled());
		expect(empty).not.toHaveProperty('port');
		expect(empty).toMatchObject({
			host: 'imap.example.org',
			security: 'tls',
			mailbox: 'INBOX',
			senders: ['shop@example.com', 'other@example.org'],
			start_date: '2026-10-24'
		});
		expect(settingsFromDraft({ ...filled(), port: ' 1143 ' }).port).toBe(1143);
	});

	it('round-trips stored settings', () => {
		const settings = {
			host: 'h.example',
			security: 'starttls',
			port: 143,
			username: 'u',
			mailbox: 'Receipts',
			senders: ['a@b.de', 'c@d.de'],
			start_date: '2026-01-02'
		};
		expect(settingsFromDraft(draftFromSettings(settings))).toEqual(settings);
	});

	it('checks what it can before a round trip, by setting key', () => {
		expect(problemsOf(filled())).toEqual({});
		const bad = problemsOf({
			...filled(),
			host: 'https://x',
			port: '70000',
			username: ' ',
			senders: 'not-an-address'
		});
		expect(Object.keys(bad).sort()).toEqual(['host', 'port', 'senders', 'username']);
		expect(problemsOf({ ...filled(), senders: '\n' }).senders).toMatch(/at least one/);
		expect(fieldOfSetting('senders')).toBe('senders');
		expect(fieldOfSetting('nope')).toBeNull();
	});
});
