import { describe, expect, it } from 'vitest';
import {
	DEFAULT_PRIORITY,
	emptyForm,
	formFromRule,
	formKey,
	hasCondition,
	isDirty,
	isPreviewable,
	parsePriority,
	previewMatchesForm,
	saveBlock,
	toFields,
	type RuleForm,
	type SaveState
} from './form.js';
import { rule } from './fixtures.js';

const ready: SaveState = {
	previewCurrent: true,
	previewFailed: false,
	saving: false,
	unchanged: false
};

function form(over: Partial<RuleForm> = {}): RuleForm {
	return { ...emptyForm('payee'), name: 'Rent', target: 5, name_prefix: 'Landlord', ...over };
}

describe('parsePriority', () => {
	it('takes a blank as the default and a whole number as itself', () => {
		expect(parsePriority('')).toBe(DEFAULT_PRIORITY);
		expect(parsePriority('  ')).toBe(DEFAULT_PRIORITY);
		expect(parsePriority('50')).toBe(50);
		expect(parsePriority(' -3 ')).toBe(-3);
	});

	it('refuses anything else', () => {
		expect(parsePriority('1.5')).toBeNull();
		expect(parsePriority('abc')).toBeNull();
		expect(parsePriority('99999999999')).toBeNull();
	});
});

describe('toFields', () => {
	it('sends the one target the rule sets, trimmed conditions and nulls for the rest', () => {
		const fields = toFields(
			form({ sets: 'payee', target: 5, name_prefix: '  PAYPAL * ', purpose_regex: '  ' })
		);

		expect(fields).toEqual({
			name: 'Rent',
			sets: 'payee',
			counter_account_id: null,
			payee_id: 5,
			category_id: null,
			condition_payee_id: null,
			counterparty_ref: null,
			mandate_ref: null,
			name_exact: null,
			name_prefix: 'PAYPAL *',
			purpose_regex: null,
			booking_text: null,
			priority: 100
		});
	});

	it('keeps the payee condition for a category rule only', () => {
		expect(
			toFields(form({ sets: 'category', target: 2, condition_payee_id: 9 })).condition_payee_id
		).toBe(9);
		expect(
			toFields(form({ sets: 'payee', target: 2, condition_payee_id: 9 })).condition_payee_id
		).toBeNull();
	});

	it('names a preview of an unnamed rule, but never a save', () => {
		expect(toFields(form({ name: '  ' }), { forPreview: true }).name).toBe('Untitled rule');
		expect(toFields(form({ name: '  ' })).name).toBe('');
	});

	it('uses the typed priority', () => {
		expect(toFields(form({ priority: '20' })).priority).toBe(20);
	});
});

describe('formFromRule', () => {
	it('is the inverse of toFields for a stored rule', () => {
		const stored = rule({
			sets: 'counter_account',
			category_id: null,
			counter_account_id: 3,
			mandate_ref: 'M-1',
			priority: 30
		});

		const back = toFields(formFromRule(stored));

		expect(back).toMatchObject({
			name: 'Landlord',
			sets: 'counter_account',
			counter_account_id: 3,
			mandate_ref: 'M-1',
			priority: 30
		});
	});

	it('shows the default priority as blank', () => {
		expect(formFromRule(rule()).priority).toBe('');
	});
});

describe('what a preview needs', () => {
	it('wants a target and a condition', () => {
		expect(isPreviewable(form())).toBe(true);
		expect(isPreviewable(form({ target: null }))).toBe(false);
		expect(isPreviewable(form({ name_prefix: '' }))).toBe(false);
		expect(isPreviewable(form({ priority: 'x' }))).toBe(false);
	});

	it('counts a payee condition only on a category rule', () => {
		const onlyPayee = { ...emptyForm('category'), target: 1, condition_payee_id: 4 };
		expect(hasCondition(onlyPayee)).toBe(true);
		expect(hasCondition({ ...onlyPayee, sets: 'payee' })).toBe(false);
	});
});

describe('the form against its preview', () => {
	it('matches a preview taken for the same request, however it was typed', () => {
		const key = formKey(form({ name_prefix: 'Landlord' }));

		expect(previewMatchesForm(key, form({ name_prefix: ' Landlord ' }))).toBe(true);
		expect(previewMatchesForm(key, form({ name_prefix: 'Landlords' }))).toBe(false);
		expect(previewMatchesForm(key, form({ target: 6 }))).toBe(false);
		expect(previewMatchesForm(null, form())).toBe(false);
	});

	it('is dirty once it differs from where it started', () => {
		const start = formKey(form());

		expect(isDirty(form(), start)).toBe(false);
		expect(isDirty(form({ booking_text: 'SEPA' }), start)).toBe(true);
	});
});

describe('saveBlock', () => {
	it('is open when everything is in place', () => {
		expect(saveBlock(form(), ready)).toBeNull();
	});

	it('says what is missing, in the order the form asks for it', () => {
		expect(saveBlock(form({ name: ' ' }), ready)).toMatch(/name/);
		expect(saveBlock(form({ target: null }), ready)).toMatch(/payee/);
		expect(saveBlock(form({ name_prefix: '' }), ready)).toMatch(/condition/);
		expect(saveBlock(form({ priority: 'x' }), ready)).toMatch(/priority/);
	});

	it('waits for a preview of this very form', () => {
		expect(saveBlock(form(), { ...ready, previewCurrent: false })).toMatch(/preview/);
		expect(saveBlock(form(), { ...ready, previewFailed: true })).toMatch(/preview/);
	});

	it('refuses an unchanged rule and a save under way', () => {
		expect(saveBlock(form(), { ...ready, unchanged: true })).toMatch(/changed/);
		expect(saveBlock(form(), { ...ready, saving: true })).toMatch(/Saving/);
	});
});
