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
import { newConditionRow, type ConditionRow } from './conditions.js';
import { rule } from './fixtures.js';

const ready: SaveState = {
	previewCurrent: true,
	previewFailed: false,
	saving: false,
	unchanged: false
};

function row(
	value: string,
	field: ConditionRow['field'] = 'counterparty_name',
	op: ConditionRow['op'] = 'starts_with'
) {
	return newConditionRow({ field, op, value });
}

function form(over: Partial<RuleForm> = {}): RuleForm {
	return {
		...emptyForm('payee'),
		name: 'Rent',
		target: 5,
		conditions: [row('Landlord')],
		...over
	};
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
	it('sends the one target the rule sets, the trimmed conditions and nulls for the rest', () => {
		const fields = toFields(
			form({
				sets: 'payee',
				target: 5,
				conditions: [row('  PAYPAL * '), row('cloud|hosting', 'purpose', 'regex')]
			})
		);

		expect(fields).toEqual({
			name: 'Rent',
			sets: 'payee',
			counter_account_id: null,
			payee_id: 5,
			category_id: null,
			conditions: [
				{ field: 'counterparty_name', op: 'starts_with', value: 'PAYPAL *' },
				{ field: 'purpose', op: 'regex', value: 'cloud|hosting' }
			],
			priority: 100
		});
	});

	it('leaves out a row with no value and keeps the order of the others', () => {
		const fields = toFields(
			form({ conditions: [row('A'), row('  '), row('B', 'purpose', 'contains'), row('')] })
		);

		expect(fields.conditions).toEqual([
			{ field: 'counterparty_name', op: 'starts_with', value: 'A' },
			{ field: 'purpose', op: 'contains', value: 'B' }
		]);
	});

	it('sends the same field twice when the user asked for it', () => {
		const fields = toFields(
			form({ conditions: [row('A', 'purpose', 'contains'), row('B', 'purpose', 'contains')] })
		);

		expect(fields.conditions).toHaveLength(2);
	});

	it('sends a payee row like any condition, and leaves a blank one out', () => {
		const conditions = [row('Landlord'), row('9', 'payee', 'is'), row('', 'payee', 'is')];

		expect(toFields(form({ sets: 'category', target: 2, conditions })).conditions).toEqual([
			{ field: 'counterparty_name', op: 'starts_with', value: 'Landlord' },
			{ field: 'payee', op: 'is', value: '9' }
		]);
	});

	it('keeps the payee condition for a category rule only', () => {
		const conditions = [row('9', 'payee', 'is')];

		expect(toFields(form({ sets: 'payee', target: 2, conditions })).conditions).toEqual([]);
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
			conditions: [
				{ field: 'mandate_ref', op: 'equals', value: 'M-1' },
				{ field: 'purpose', op: 'regex', value: 'miete|rent' }
			],
			priority: 30
		});

		const back = toFields(formFromRule(stored));

		expect(back).toMatchObject({
			name: 'Landlord',
			sets: 'counter_account',
			counter_account_id: 3,
			conditions: stored.conditions,
			priority: 30
		});
	});

	it('loads a payee condition as a row of its own', () => {
		const loaded = formFromRule(rule({ conditions: [{ field: 'payee', op: 'is', value: '4' }] }));

		expect(loaded.conditions).toHaveLength(1);
		expect(loaded.conditions[0]).toMatchObject({ field: 'payee', op: 'is', value: '4' });
	});

	it('gives a rule without conditions the one blank row', () => {
		const loaded = formFromRule(rule({ conditions: [] }));

		expect(loaded.conditions).toHaveLength(1);
		expect(loaded.conditions[0].value).toBe('');
	});

	it('shows the default priority as blank', () => {
		expect(formFromRule(rule()).priority).toBe('');
	});
});

describe('what a preview needs', () => {
	it('wants a target and a condition', () => {
		expect(isPreviewable(form())).toBe(true);
		expect(isPreviewable(form({ target: null }))).toBe(false);
		expect(isPreviewable(form({ conditions: [row('')] }))).toBe(false);
		expect(isPreviewable(form({ priority: 'x' }))).toBe(false);
	});

	it('counts a payee condition only on a category rule', () => {
		const onlyPayee = {
			...emptyForm('category'),
			target: 1,
			conditions: [row('4', 'payee', 'is')]
		};
		expect(hasCondition(onlyPayee)).toBe(true);
		expect(hasCondition({ ...onlyPayee, sets: 'payee' })).toBe(false);
	});
});

describe('the form against its preview', () => {
	it('matches a preview taken for the same request, however it was typed', () => {
		const key = formKey(form({ conditions: [row('Landlord')] }));

		expect(previewMatchesForm(key, form({ conditions: [row(' Landlord ')] }))).toBe(true);
		expect(previewMatchesForm(key, form({ conditions: [row('Landlord'), row('')] }))).toBe(true);
		expect(previewMatchesForm(key, form({ conditions: [row('Landlords')] }))).toBe(false);
		expect(
			previewMatchesForm(
				key,
				form({ conditions: [row('Landlord', 'counterparty_name', 'equals')] })
			)
		).toBe(false);
		expect(previewMatchesForm(key, form({ target: 6 }))).toBe(false);
		expect(previewMatchesForm(null, form())).toBe(false);
	});

	it('is dirty once it differs from where it started', () => {
		const start = formKey(form());

		expect(isDirty(form(), start)).toBe(false);
		expect(
			isDirty(form({ conditions: [row('Landlord'), row('SEPA', 'booking_text')] }), start)
		).toBe(true);
		expect(isDirty(form({ conditions: [row('Landlord'), row('')] }), start)).toBe(false);
	});
});

describe('saveBlock', () => {
	it('is open when everything is in place', () => {
		expect(saveBlock(form(), ready)).toBeNull();
	});

	it('says what is missing, in the order the form asks for it', () => {
		expect(saveBlock(form({ name: ' ' }), ready)).toMatch(/name/);
		expect(saveBlock(form({ target: null }), ready)).toMatch(/payee/);
		expect(saveBlock(form({ conditions: [row('')] }), ready)).toMatch(/condition/);
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
