import { describe, expect, it } from 'vitest';
import { account, entry } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { source } from '#lib/rules/fixtures.js';
import {
	anchorEntry,
	entryLabel,
	sourceGroups,
	stateText,
	unitShape,
	unitTitle
} from './describe.js';

const lookups = buildLookups({
	accounts: [account({ id: 1, name: 'Giro' }), account({ id: 2, name: 'Savings' })]
});

describe('stateText', () => {
	it('says Confirmed, or the reasons in plain words', () => {
		expect(stateText({ confirmed: true, reasons: [] })).toBe('Confirmed');
		expect(stateText({ confirmed: false, reasons: ['incomplete', 'non_standing_keys'] })).toBe(
			'Incomplete · Proposals to check'
		);
		expect(stateText({ confirmed: false, reasons: ['unpaired_transfer'] })).toBe(
			'Waiting for its partner'
		);
		expect(stateText({ confirmed: false, reasons: [] })).toBe('In review');
	});
});

describe('unitShape and title', () => {
	const flow = entry({ id: 1, display_text: 'REWE Markt' });
	it('a single entry is titled by its text', () => {
		expect(unitShape([flow])).toBe('single');
		expect(unitTitle({ anchor_entry_id: 1, entries: [flow] }, lookups)).toBe('REWE Markt');
	});

	it('a split says how many entries', () => {
		const entries = [flow, entry({ id: 2, source_transaction_id: 5 })];
		expect(unitShape(entries)).toBe('split');
		expect(unitTitle({ anchor_entry_id: 1, entries }, lookups)).toBe('REWE Markt (split in 2)');
	});

	it('a pair names its accounts, outgoing first', () => {
		const entries = [
			entry({
				id: 1,
				account_id: 2,
				amount: { amount: 5000, currency: 'EUR' },
				type: 'transfer',
				counterpart_entry_id: 2
			}),
			entry({
				id: 2,
				account_id: 1,
				amount: { amount: -5000, currency: 'EUR' },
				type: 'transfer',
				counterpart_entry_id: 1
			})
		];
		expect(unitShape(entries)).toBe('pair');
		expect(unitTitle({ anchor_entry_id: 1, entries }, lookups)).toBe('Transfer Giro → Savings');
	});

	it('falls back from text to counterparty to hand-entered', () => {
		expect(
			entryLabel(entry({ display_text: null, source: source({ counterparty_name: 'Acme' }) }))
		).toBe('Acme');
		expect(entryLabel(entry({ display_text: null, authored: true }))).toBe('Entered by hand');
		expect(entryLabel(entry({ id: 9, display_text: null }))).toBe('Entry 9');
	});

	it('the anchor is the named entry, else the first', () => {
		const entries = [entry({ id: 4 }), entry({ id: 7 })];
		expect(anchorEntry({ anchor_entry_id: 7, entries })?.id).toBe(7);
		expect(anchorEntry({ anchor_entry_id: 1, entries })?.id).toBe(4);
	});
});

describe('sourceGroups', () => {
	it('groups a split under its one source; hand-entered entries are listed like the others', () => {
		const src = source({ counterparty_name: 'Acme' });
		const groups = sourceGroups([
			entry({ id: 1, source: src, source_transaction_id: 5 }),
			entry({ id: 2, source: src, source_transaction_id: 5 }),
			entry({ id: 3, authored: true, source: src, source_transaction_id: 6 }),
			entry({ id: 4 })
		]);
		expect(groups).toHaveLength(2);
		expect(groups[0]).toMatchObject({ key: 5, authored: false, entryIds: [1, 2], source: src });
		expect(groups[1]).toMatchObject({ key: 6, authored: true, entryIds: [3], source: src });
	});

	it('puts a hand-entered entry without a source in one group of its own', () => {
		const groups = sourceGroups([
			entry({ id: 1, authored: true, source: null }),
			entry({ id: 2, authored: true, source: null })
		]);
		expect(groups).toEqual([{ key: null, source: null, authored: true, entryIds: [1, 2] }]);
	});
});
