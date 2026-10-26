import { describe, expect, it } from 'vitest';
import { payee } from '#lib/ledger/fixtures.js';
import type { PayeeDeleteOut, PayeeMergeOut } from '#lib/types/domain.js';
import { payeeDeleteSummary, payeeMergeSummary } from './summary.js';

const mergeOut = (over: Partial<PayeeMergeOut> = {}): PayeeMergeOut => ({
	dry_run: true,
	source_id: 1,
	target: payee({ id: 2, name: 'REWE Markt' }),
	entry_count: 7,
	entry_ids: [],
	setting_rule_ids: [4],
	condition_rule_ids: [5, 6],
	settle: null,
	...over
});

describe('payeeMergeSummary', () => {
	it('counts the entries and the two kinds of rules', () => {
		const summary = payeeMergeSummary(mergeOut());

		expect(summary.totals).toBe('Repoints 7 entries');
		expect(summary.rules).toEqual([
			'1 rule setting it repointed',
			'2 rules naming it as a condition repointed'
		]);
	});

	it('leaves out the rule lines that are zero', () => {
		const summary = payeeMergeSummary(mergeOut({ setting_rule_ids: [], condition_rule_ids: [] }));

		expect(summary.rules).toEqual([]);
	});

	it('says the target keeps its own attributes', () => {
		const summary = payeeMergeSummary(mergeOut());

		expect(summary.notes).toContain('REWE Markt keeps its own name, note, icon and colour.');
	});
});

const deleteOut = (over: Partial<PayeeDeleteOut> = {}): PayeeDeleteOut => ({
	dry_run: true,
	deletable: true,
	deleted: false,
	deleted_rule_ids: [],
	held: { entries: 0 },
	payee: payee({ name: 'REWE' }),
	rules: [],
	dangling_rules: [],
	settle: null,
	...over
});

describe('payeeDeleteSummary', () => {
	it('counts the rules that set the payee (deleted) apart from those that only test it', () => {
		const summary = payeeDeleteSummary(
			deleteOut({
				rules: [{ id: 1, name: 'REWE → Groceries', sets: 'payee', role: 'sets' }],
				dangling_rules: [
					{ id: 2, name: 'Fuel', sets: 'category', role: 'condition' },
					{ id: 3, name: 'Snacks', sets: 'category', role: 'condition' }
				]
			})
		);

		expect(summary.deletable).toBe(true);
		expect(summary.deleted).toEqual({
			heading: '1 rule sets this payee and will be deleted:',
			names: ['REWE → Groceries']
		});
		expect(summary.dangling).toEqual({
			heading: '2 rules test this payee and will stop matching:',
			names: ['Fuel', 'Snacks']
		});
	});

	it('has no groups when no rule is involved', () => {
		const summary = payeeDeleteSummary(deleteOut());

		expect(summary.deleted).toBeNull();
		expect(summary.dangling).toBeNull();
	});

	it('refuses with the entries that reference it', () => {
		const summary = payeeDeleteSummary(deleteOut({ deletable: false, held: { entries: 12 } }));

		expect(summary.reason).toBe(
			'REWE cannot be deleted: it is referenced by 12 entries. Merge it into another payee instead.'
		);
	});
});
