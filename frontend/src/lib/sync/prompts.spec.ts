import { describe, expect, it } from 'vitest';
import type { PromptBody } from '#lib/api/sync.js';
import { promptFieldLabel, promptMoment, promptTitle, promptVerb, subjectLabel } from './prompts.js';

const tan = (medium: 'text' | 'image' | 'decoupled'): PromptBody => ({
	kind: 'tan',
	medium,
	challenge: 'Enter the TAN',
	method: 'pushTAN',
	image_b64: null,
	image_mime: null
});

describe('subjectLabel', () => {
	it('names the known subjects', () => {
		expect(subjectLabel('pin')).toBe('PIN');
		expect(subjectLabel('password')).toBe('Password');
		expect(subjectLabel('tan_mechanism')).toBe('TAN method');
		expect(subjectLabel('tan_medium')).toBe('TAN medium');
		expect(subjectLabel('tan_medium_name')).toBe('Name of the TAN medium');
	});

	it('shows an unknown subject as given', () => {
		expect(subjectLabel('security_question')).toBe('security_question');
	});
});

describe('the verb of a prompt', () => {
	it('is "Sign in" for a secret, "Send TAN" for a typed or photographed TAN', () => {
		expect(promptVerb({ kind: 'secret', subject: 'pin' })).toBe('Sign in');
		expect(promptVerb(tan('text'))).toBe('Send TAN');
		expect(promptVerb(tan('image'))).toBe('Send TAN');
	});

	it('is "Continue" for a choice and a text', () => {
		expect(promptVerb({ kind: 'choice', subject: 'tan_mechanism', options: [] })).toBe('Continue');
		expect(promptVerb({ kind: 'text', subject: 'tan_medium_name' })).toBe('Continue');
	});

	it('is none for a decoupled confirmation', () => {
		expect(promptVerb(tan('decoupled'))).toBeNull();
	});
});

describe('the title and the field of a prompt', () => {
	it('is titled by what it asks and the login', () => {
		expect(promptTitle({ kind: 'secret', subject: 'pin' }, 'Giro login')).toBe('PIN for Giro login');
		expect(promptTitle({ kind: 'secret', subject: 'password' }, 'Giro login')).toBe(
			'Password for Giro login'
		);
		expect(promptTitle(tan('text'), 'Giro login')).toBe('TAN for Giro login');
		expect(promptTitle(tan('decoupled'), 'Giro login')).toBe('Confirmation for Giro login');
		expect(
			promptTitle({ kind: 'choice', subject: 'tan_mechanism', options: [] }, 'Giro login')
		).toBe('TAN method for Giro login');
	});

	it('labels the field by the subject, a TAN field "TAN", a decoupled prompt none', () => {
		expect(promptFieldLabel({ kind: 'secret', subject: 'pin' })).toBe('PIN');
		expect(promptFieldLabel({ kind: 'text', subject: 'tan_medium_name' })).toBe(
			'Name of the TAN medium'
		);
		expect(promptFieldLabel(tan('image'))).toBe('TAN');
		expect(promptFieldLabel(tan('decoupled'))).toBeNull();
	});

	it('describes the moment', () => {
		expect(promptMoment(null, null)).toBe('Signing in.');
		expect(promptMoment(10, 'Giro')).toBe('Fetching Giro.');
	});
});
