import { describe, expect, it } from 'vitest';
import { payee } from '#lib/ledger/fixtures.js';
import type { PayeeDeleteOut, PayeeMergeOut } from '#lib/types/domain.js';
import { payeeDeleteSummary, payeeMergeSummary } from './summary.js';

const mergeOut = (over: Partial<PayeeMergeOut> = {}): PayeeMergeOut => ({
	dry_run: true,
	source_id: 1,
	target: { ...payee({ id: 2, name: 'REWE Markt' }), document_provider: null },
	entry_count: 7,
	entry_ids: [],
	setting_rule_ids: [4],
	condition_rule_ids: [5, 6],
	document_provider_lost: false,
	source_document_provider: null,
	settle: null,
	...over
});

describe('payeeMergeSummary', () => {
	it('counts the entries and the two kinds of rules', () => {
		const summary = payeeMergeSummary(mergeOut(), payee({ name: 'REWE' }));

		expect(summary.totals).toBe('Repoints 7 entries');
		expect(summary.rules).toEqual([
			'1 rule setting it repointed',
			'2 rules naming it as a condition repointed'
		]);
		expect(summary.warnings).toEqual([]);
	});

	it('leaves out the rule lines that are zero', () => {
		const summary = payeeMergeSummary(
			mergeOut({ setting_rule_ids: [], condition_rule_ids: [] }),
			undefined
		);

		expect(summary.rules).toEqual([]);
	});

	it('warns when the source document provider would be lost, and says the target keeps its own', () => {
		const summary = payeeMergeSummary(
			mergeOut({ document_provider_lost: true, source_document_provider: 'paypal' }),
			payee({ name: 'PayPal' })
		);

		expect(summary.warnings[0]).toContain('"paypal"');
		expect(summary.notes).toContain('REWE Markt keeps its own name, note, icon and colour.');
	});
});

const deleteOut = (over: Partial<PayeeDeleteOut> = {}): PayeeDeleteOut => ({
	dry_run: true,
	deletable: true,
	deleted: false,
	deleted_rule_ids: [],
	held: { entries: 0 },
	payee: { ...payee({ name: 'REWE' }), document_provider: null },
	rules: [],
	settle: null,
	...over
});

describe('payeeDeleteSummary', () => {
	it('lists the rules that would be deleted with their role', () => {
		const summary = payeeDeleteSummary(
			deleteOut({
				rules: [
					{ id: 1, name: 'REWE → Groceries', sets: 'payee', role: 'sets' },
					{ id: 2, name: 'Fuel', sets: 'category', role: 'condition' }
				]
			})
		);

		expect(summary.deletable).toBe(true);
		expect(summary.rules).toEqual([
			'REWE → Groceries (sets this payee)',
			'Fuel (names this payee as a condition)'
		]);
	});

	it('refuses with the entries that reference it', () => {
		const summary = payeeDeleteSummary(deleteOut({ deletable: false, held: { entries: 12 } }));

		expect(summary.reason).toBe(
			'REWE cannot be deleted: it is referenced by 12 entries. Merge it into another payee instead.'
		);
	});
});
