import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { unit } from './fixtures.js';
import { account } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import {
	appendUnits,
	completableNotice,
	groupHeading,
	insertUnitEntries,
	orderByGroups,
	patchUnitEntries,
	unitsOfGroup,
	waitingDocumentReason,
	waitingOrderReason,
	waitingReason
} from './queue.js';

describe('appendUnits', () => {
	it('appends a page and skips units already held', () => {
		const held = [unit({ anchor_entry_id: 1 }), unit({ anchor_entry_id: 2 })];
		const out = appendUnits(held, [unit({ anchor_entry_id: 2 }), unit({ anchor_entry_id: 3 })]);
		expect(out.map((u) => u.anchor_entry_id)).toEqual([1, 2, 3]);
	});
});

describe('patchUnitEntries', () => {
	it('replaces entries by id inside their units and keeps the order', () => {
		const units = [unit({ anchor_entry_id: 1 }), unit({ anchor_entry_id: 2 })];
		const out = patchUnitEntries(units, [entry({ id: 2, note: 'x' }), entry({ id: 9, note: 'y' })]);
		expect(out.map((u) => u.anchor_entry_id)).toEqual([1, 2]);
		expect(out[1].entries[0].note).toBe('x');
		expect(out[0].entries[0].note).toBeNull();
		expect(out).toHaveLength(2);
	});
});

describe('insertUnitEntries', () => {
	it('puts created entries into the unit of their anchor and no other', () => {
		const units = [unit({ anchor_entry_id: 1 }), unit({ anchor_entry_id: 2 })];
		const out = insertUnitEntries(units, {
			entries: [entry({ id: 7, unit_key: 1 })],
			created: [7],
			anchor_entry_id: 1
		});
		expect(out[0].entries.map((e) => e.id)).toEqual([1, 7]);
		expect(out[1].entries.map((e) => e.id)).toEqual([2]);
	});

	it('leaves the units alone when nothing was created', () => {
		const units = [unit({ anchor_entry_id: 1 })];
		expect(insertUnitEntries(units, { entries: [] })).toEqual(units);
	});
});

describe('group wording', () => {
	it('says a transfer in the singular and N transfers otherwise', () => {
		expect(groupHeading(1, 'USD')).toBe('A transfer needs an account in USD');
		expect(groupHeading(3, 'USD')).toBe('3 transfers need an account in USD');
		expect(groupHeading(1200, 'USD')).toBe('1,200 transfers need an account in USD');
	});

	it('words the notice after an account was added', () => {
		expect(completableNotice(1)).toBe('1 unit can now be completed: refresh');
		expect(completableNotice(4)).toBe('4 units can now be completed: refresh');
	});
});

describe('orderByGroups', () => {
	const needing = (id: number, currency: string) =>
		unit({ anchor_entry_id: id, needs_account: { currency } });

	it('orders by the groups, stable by date within a group, ungrouped units last', () => {
		const units = [
			needing(1, 'USD'),
			needing(2, 'EUR'),
			needing(3, 'USD'),
			unit({ anchor_entry_id: 4 })
		];
		const groups = [
			{ currency: 'EUR', count: 1 },
			{ currency: 'USD', count: 2 }
		];
		expect(orderByGroups(units, groups).map((u) => u.anchor_entry_id)).toEqual([2, 1, 3, 4]);
		expect(unitsOfGroup(units, 'USD').map((u) => u.anchor_entry_id)).toEqual([1, 3]);
	});
});

describe('waitingReason', () => {
	const lookups = buildLookups({ accounts: [account({ id: 2, name: 'Savings' })] });

	it('names the account and what its sync covers', () => {
		expect(waitingReason({ account_id: 2, synced_through: null }, lookups)).toBe(
			'Waiting for Savings, not synced yet'
		);
		expect(waitingReason({ account_id: 2, synced_through: '2026-10-12' }, lookups)).toMatch(
			/^Waiting for Savings, synced through .*2026$/
		);
	});
});

describe('waitingDocumentReason', () => {
	it('names the provider and how far its documents are covered', () => {
		expect(waitingDocumentReason({ provider: 'amazon', covered_through: null })).toBe(
			'Waiting for a document from amazon, not synced yet'
		);
		expect(waitingDocumentReason({ provider: 'amazon', covered_through: '2026-10-12' })).toMatch(
			/^Waiting for a document from amazon, covered through .*2026$/
		);
	});
});

describe('waitingOrderReason', () => {
	it('names the order and what is not yet charged of its total, by magnitude', () => {
		expect(
			waitingOrderReason({
				order: '302-1',
				provider: 'amazon',
				charged: { amount: -3000, currency: 'EUR' },
				total: { amount: -5000, currency: 'EUR' }
			})
		).toBe('Waiting for the rest of order 302-1 from amazon: 20.00 of 50.00 not yet charged');
	});

	it('reads a refund order the same way', () => {
		expect(
			waitingOrderReason({
				order: 'R-9',
				provider: 'amazon',
				charged: { amount: 1000, currency: 'EUR' },
				total: { amount: 2500, currency: 'EUR' }
			})
		).toBe('Waiting for the rest of order R-9 from amazon: 15.00 of 25.00 not yet charged');
	});
});
