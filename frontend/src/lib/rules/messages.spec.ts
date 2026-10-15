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
	const bd = (thisRule: number, history: number, otherRules: number, other: number) => ({
		total: thisRule + history + otherRules + other,
		thisRule,
		history,
		otherRules,
		other
	});
	const saved = (breakdown: ReturnType<typeof bd> | null, settleFailed = false) =>
		doneText({ action: 'saved', name: 'Rent', breakdown, settleFailed });
	const deleted = (breakdown: ReturnType<typeof bd> | null) =>
		doneText({ action: 'deleted', name: 'Rent', breakdown, settleFailed: false });

	it('survives the address it travels in', () => {
		const done = {
			action: 'saved',
			name: 'Rent & bills',
			breakdown: bd(9, 15, 1, 2),
			settleFailed: false
		} as const;

		const url = doneUrl(done);

		expect(url.startsWith('/settings/rules?')).toBe(true);
		expect(doneFromSearch(url.split('?')[1])).toEqual(done);
	});

	it('travels without a breakdown too', () => {
		const done = { action: 'deleted', name: 'Rent', breakdown: null, settleFailed: true } as const;

		expect(doneFromSearch(doneUrl(done).split('?')[1])).toEqual(done);
	});

	it('says where the entries of a save come from', () => {
		expect(saved(bd(9, 15, 0, 0))).toBe(
			'Rule “Rent” saved. 9 entries now follow it. History then proposed it for 15 more; they stay in review for you to check.'
		);
		expect(saved(bd(9, 15, 1, 2))).toBe(
			'Rule “Rent” saved. 9 entries now follow it. History then proposed it for 15 more; they stay in review for you to check. 3 other entries were updated.'
		);
	});

	it('leaves out the parts that are zero and keeps singular and plural apart', () => {
		expect(saved(bd(1, 0, 0, 0))).toBe('Rule “Rent” saved. 1 entry now follows it.');
		expect(saved(bd(0, 1, 0, 0))).toBe(
			'Rule “Rent” saved. History proposed it for 1 entry; it stays in review for you to check.'
		);
		expect(saved(bd(2, 1, 0, 0))).toContain(
			'History then proposed it for 1 more; it stays in review'
		);
		expect(saved(bd(2, 0, 0, 1))).toBe(
			'Rule “Rent” saved. 2 entries now follow it. 1 other entry was updated.'
		);
		expect(saved(bd(0, 0, 1, 2))).toBe('Rule “Rent” saved. 3 entries were updated.');
	});

	it('says nothing changed when nothing did', () => {
		expect(saved(bd(0, 0, 0, 0))).toBe('Rule “Rent” saved. No entries changed.');
		expect(deleted(bd(0, 0, 0, 0))).toBe('Rule “Rent” deleted. No entries changed.');
	});

	it('says what a delete changed, leaving out zero parts', () => {
		expect(deleted(bd(0, 1, 3, 2))).toBe(
			'Rule “Rent” deleted. 6 entries were updated: 3 now follow another rule, 1 got a proposal from history, 2 changed otherwise.'
		);
		expect(deleted(bd(0, 0, 1, 0))).toBe(
			'Rule “Rent” deleted. 1 entry was updated: 1 now follows another rule.'
		);
	});

	it('names only the write when settling told nothing, and warns when it failed', () => {
		expect(saved(null)).toBe('Rule “Rent” saved.');
		expect(saved(null, true)).toBe(
			'Rule “Rent” saved. Derived figures may be stale until the next action.'
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
