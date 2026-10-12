import { describe, expect, it } from 'vitest';
import { doneFromSearch, doneText, doneUrl, describeRuleError, fieldErrors } from './messages.js';
import { groupRules } from './groups.js';
import { ledgerLink, ruleUrl } from './links.js';
import { rule } from './fixtures.js';

describe('fieldErrors', () => {
	it('puts an invalid regex at its field', () => {
		expect(
			fieldErrors({ kind: 'invalid_rule', field: 'purpose_regex', message: 'unterminated' })
		).toEqual({ purpose_regex: 'unterminated' });
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
	it('points a row at its booking day in its account', () => {
		expect(ledgerLink({ booked_on: '2026-10-01', account_id: 2 })).toBe(
			'/ledger?from=2026-10-01&to=2026-10-01&account_id=2'
		);
	});

	it('points a rule at its page', () => {
		expect(ruleUrl(9)).toBe('/settings/rules/9');
	});
});
