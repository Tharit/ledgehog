import { describe, expect, it } from 'vitest';
import { draftFromSettings as csvFrom, emptyDraft as csvEmpty } from './csv-profile.js';
import { hasSettingsForm, settingsFormOf } from './forms.js';

describe('the settings form registry', () => {
	it('has a form for csv and fints, none for another importer', () => {
		expect(hasSettingsForm('csv')).toBe(true);
		expect(hasSettingsForm('fints')).toBe(true);
		expect(hasSettingsForm('nope')).toBe(false);
		expect(hasSettingsForm('constructor')).toBe(false);
		expect(settingsFormOf('nope')).toBeNull();
	});

	it('has a form for camt that holds no settings', () => {
		const form = settingsFormOf('camt')!;
		expect(form.emptyDraft()).toEqual({});
		expect(form.settingsFromDraft(form.draftFromSettings({}))).toEqual({});
		expect(form.fieldOfRefusal('anything')).toBeNull();
	});

	it('is the csv adapter for csv, unchanged: the profile round-trips', () => {
		const form = settingsFormOf('csv')!;
		expect(form.emptyDraft()).toEqual(csvEmpty());
		const settings = {
			header_marker: ['Buchung', 'Betrag'],
			booked_on: 'Buchung',
			date_format: 'dd.MM.yyyy',
			amount: { column: 'Betrag', credit: null, debit: null }
		};
		expect(form.draftFromSettings(settings)).toEqual(csvFrom(settings));
		const again = form.settingsFromDraft(form.draftFromSettings(settings));
		expect(again).toMatchObject(settings);
		expect(form.fieldOfRefusal('amount.credit')).toBe('amount');
		expect(form.fieldOfRefusal('nothing_like_it')).toBeNull();
		expect(form.problems).toBeUndefined();
	});

	describe('fints', () => {
		const form = settingsFormOf('fints')!;

		it('starts empty', () => {
			expect(form.emptyDraft()).toEqual({ url: '', bankCode: '', userId: '', customerId: '' });
		});

		it('reads stored settings, a missing customer_id as empty', () => {
			const stored = { url: 'https://b.example/fints', bank_code: '12345678', user_id: 'me' };
			expect(form.draftFromSettings(stored)).toEqual({
				url: 'https://b.example/fints',
				bankCode: '12345678',
				userId: 'me',
				customerId: ''
			});
			expect(form.draftFromSettings({ customer_id: 'c1' }).customerId).toBe('c1');
		});

		it('writes settings and omits an empty customer_id', () => {
			const draft = {
				url: ' https://b.example/fints ',
				bankCode: '12345678',
				userId: 'me',
				customerId: '  '
			};
			expect(form.settingsFromDraft(draft)).toEqual({
				url: 'https://b.example/fints',
				bank_code: '12345678',
				user_id: 'me'
			});
			expect(form.settingsFromDraft({ ...draft, customerId: 'c1' })).toMatchObject({
				customer_id: 'c1'
			});
		});

		it('checks the draft before saving', () => {
			expect(Object.keys(form.problems!(form.emptyDraft())).sort()).toEqual([
				'bank_code',
				'url',
				'user_id'
			]);
			const ok = { url: 'https://b.example', bankCode: '12345678', userId: 'me', customerId: '' };
			expect(form.problems!(ok)).toEqual({});
			expect(form.problems!({ ...ok, url: 'http://b.example' })).toHaveProperty('url');
			expect(form.problems!({ ...ok, bankCode: '1234567' })).toHaveProperty('bank_code');
			expect(form.problems!({ ...ok, bankCode: '1234567a' })).toHaveProperty('bank_code');
		});

		it('maps a refused setting key to its field', () => {
			expect(form.fieldOfRefusal('bank_code')).toBe('bank_code');
			expect(form.fieldOfRefusal('customer_id')).toBe('customer_id');
			expect(form.fieldOfRefusal('other')).toBeNull();
		});
	});
});
