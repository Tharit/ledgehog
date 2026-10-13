import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { unit } from './fixtures.js';
import { appendUnits, patchUnitEntries } from './queue.js';

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
