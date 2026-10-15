import { describe, expect, it } from 'vitest';
import { doneFromSearch, doneText, doneUrl, describeRuleError, fieldErrors } from './messages.js';
import { groupRules } from './groups.js';
import { ruleUrl } from './links.js';
import { rule } from './fixtures.js';

describe('fieldErrors', () => {
	it('puts a condition the server refused at its row', () => {
		expect(
			fieldErrors({
				kind: 'invalid_rule',
				field: 'conditions[1].value',
				message: 'conditions[1]: the regex does not compile (at position 3)'
			})
		).toEqual({ rows: { 1: 'The regex does not compile (at position 3)' } });
	});

	it('puts a refused condition at the editor row it came from, blank rows left out', () => {
		// the editor has rows 0 (blank), 1, 2 (blank), 3; the request carried rows 1 and 3
		expect(
			fieldErrors(
				{
					kind: 'invalid_rule',
					field: 'conditions[1].op',
					message: 'conditions[1]: the operator is not one a rule knows'
				},
				[1, 3]
			)
		).toEqual({ rows: { 3: 'The operator is not one a rule knows' } });
	});

	it('puts a missing condition at the list of conditions', () => {
		expect(
			fieldErrors({
				kind: 'invalid_rule',
				field: 'conditions',
				message: 'a rule needs at least one condition'
			})
		).toEqual({ conditions: 'a rule needs at least one condition' });
	});

	it('reads the rows of a validation error given as segments, the first message per row', () => {
		expect(
			fieldErrors({
				kind: 'validation',
				problems: [
					{ field: 'conditions[0].value', message: 'too long' },
					{ field: 'conditions[0].op', message: 'other' },
					{ field: 'conditions[2].value', message: 'bad' }
				]
			})
		).toEqual({ rows: { 0: 'Too long', 2: 'Bad' } });
	});

	it('puts a stale payee on its row, by the editor position', () => {
		expect(
			fieldErrors(
				{ kind: 'stale_reference', field: 'conditions[1].value', entity: 'payee' },
				[0, 2, 3]
			)
		).toEqual({ rows: { 2: 'This payee no longer exists.' } });
	});

	it('puts a taken name at the name', () => {
		expect(fieldErrors({ kind: 'duplicate_name' }).name).toMatch(/already exists/);
	});

	it('maps every target id field to the target', () => {
		for (const field of ['category_id', 'payee_id', 'counter_account_id']) {
			expect(Object.keys(fieldErrors({ kind: 'stale_reference', field, entity: 'x' }))).toEqual([
				'target'
			]);
		}
	});

	it('reads the fields of a validation error and ignores the unknown ones', () => {
		expect(
			fieldErrors({
				kind: 'validation',
				problems: [
					{ field: 'name', message: 'too short' },
					{ field: 'surprise', message: 'x' }
				]
			})
		).toEqual({ name: 'too short' });
	});

	it('says an unknown place in one line, not at a field', () => {
		expect(
			describeRuleError({ kind: 'invalid_rule', field: 'sets', message: 'bad sets' })
		).toContain('bad sets');
		expect(
			describeRuleError({ kind: 'invalid_rule', field: 'conditions[0].value', message: 'x' })
		).toMatch(/highlighted/);
	});

	it('has none for a failure that is not about a field', () => {
		expect(fieldErrors(null)).toEqual({});
		expect(fieldErrors({ kind: 'network' })).toEqual({});
	});
});

describe('describeRuleError', () => {
	it('says what a moved result was and is', () => {
		const text = describeRuleError({ kind: 'filter_result_changed', expected: 3, actual: 1200 });

		expect(text).toContain('3 entries before');
		expect(text).toContain('1,200 now');
	});

	it('names what a stale reference pointed at', () => {
		expect(
			describeRuleError({ kind: 'stale_reference', field: 'payee_id', entity: 'payee' })
		).toMatch(/^Payee you chose no longer exists/);
	});
});

describe('the notice after a write', () => {
	it('survives the address it travels in', () => {
		const done = {
			action: 'saved',
			name: 'Rent & bills',
			touched: 3,
			settleFailed: false
		} as const;

		const url = doneUrl(done);

		expect(url.startsWith('/settings/rules?')).toBe(true);
		expect(doneFromSearch(url.split('?')[1])).toEqual(done);
	});

	it('says what settled', () => {
		expect(doneText({ action: 'saved', name: 'Rent', touched: 3, settleFailed: false })).toBe(
			'Rule “Rent” saved. Settling touched 3 entries.'
		);
		expect(doneText({ action: 'deleted', name: 'Rent', touched: 1, settleFailed: false })).toBe(
			'Rule “Rent” deleted. Settling touched 1 entry.'
		);
		expect(doneText({ action: 'saved', name: 'Rent', touched: 0, settleFailed: true })).toContain(
			'No entries needed settling.'
		);
		expect(doneText({ action: 'saved', name: 'Rent', touched: 0, settleFailed: true })).toContain(
			'stale'
		);
	});

	it('is not there without an action', () => {
		expect(doneFromSearch('')).toBeNull();
		expect(doneFromSearch('done=exploded&name=x')).toBeNull();
	});
});

describe('groupRules', () => {
	it('groups by what a rule sets, in evaluation order, keeping the server order within', () => {
		const groups = groupRules([
			rule({ id: 1, sets: 'category' }),
			rule({ id: 2, sets: 'counter_account', category_id: null, counter_account_id: 1 }),
			rule({ id: 3, sets: 'category' })
		]);

		expect(groups.map((g) => g.sets)).toEqual(['counter_account', 'category']);
		expect(groups[1].rules.map((r) => r.id)).toEqual([1, 3]);
	});

	it('leaves out an empty group', () => {
		expect(groupRules([])).toEqual([]);
	});
});

describe('links', () => {
	it('points a rule at its page', () => {
		expect(ruleUrl(9)).toBe('/settings/rules/9');
	});
});
