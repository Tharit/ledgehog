import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { selectionReason } from './selection.js';
import { unit } from './fixtures.js';

const of = (...entries: ReturnType<typeof entry>[]) => unit({ entries });

describe('selectionReason', () => {
	it('is null for a flow whose category is only proposed', () => {
		const proposed = entry({
			id: 1,
			category_id: 10,
			review_flags: ['unconfirmed'],
			derivation: { category: { pass: 'history', basis: { agree: 3, of: 4, since: '2026-03-14' } } }
		});
		expect(selectionReason(of(proposed))).toBeNull();
	});

	it('ignores a stale unit state: the rows decide', () => {
		const u = {
			...of(entry({ id: 1, category_id: 10, review_flags: [] })),
			state: { confirmed: false, reasons: ['incomplete', 'unpaired_transfer'] }
		} as ReturnType<typeof unit>;
		expect(selectionReason(u)).toBeNull();
	});

	it('refuses a flow without a category, and a typeless entry', () => {
		expect(
			selectionReason(of(entry({ id: 1, category_id: null, review_flags: ['unclassified'] })))
		).toBe('No category yet');
		expect(selectionReason(of(entry({ id: 1, type: null })))).toBe('No category yet');
	});

	it('refuses an unpaired transfer, accepts a paired one', () => {
		const leg = { id: 1, type: 'transfer' as const, category_id: null, review_flags: [] };
		expect(selectionReason(of(entry({ ...leg, counterpart_entry_id: null })))).toBe(
			'Transfer not paired'
		);
		expect(selectionReason(of(entry({ ...leg, counterpart_entry_id: 2 })))).toBeNull();
	});

	it('refuses a pending model answer and a committed unit', () => {
		expect(selectionReason(of(entry({ id: 1, category_id: 10, model_pending: true })))).toBe(
			'The model is still looking'
		);
		expect(selectionReason(of(entry({ id: 1, category_id: 10 })), true)).toBe('Already committed');
	});
});
