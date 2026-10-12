import { describe, expect, it } from 'vitest';
import { entry } from './fixtures.js';
import { NO_IDS, patchTagIds, rowsOutOfTagFilter, withIds } from './patch.js';

const rows = [entry({ id: 3 }), entry({ id: 2, tag_ids: [7] }), entry({ id: 1 })];

describe('patchTagIds', () => {
	it('writes tag ids into the named rows and keeps rows and order', () => {
		const out = patchTagIds(rows, [{ id: 2, tag_ids: [7, 8] }]);

		expect(out.map((e) => e.id)).toEqual([3, 2, 1]);
		expect(out[1].tag_ids).toEqual([7, 8]);
		expect(out[0]).toBe(rows[0]);
	});

	it('ignores an entry that is not held', () => {
		expect(patchTagIds(rows, [{ id: 99, tag_ids: [1] }]).map((e) => e.id)).toEqual([3, 2, 1]);
	});
});

describe('rowsOutOfTagFilter', () => {
	it('marks touched rows that no longer carry a filtered tag', () => {
		const touched = withIds(NO_IDS, [1, 2]);

		const out = rowsOutOfTagFilter(rows, touched, [7]);

		expect([...out]).toEqual([1]);
	});

	it('marks nothing without a tag filter or without touched rows', () => {
		expect(rowsOutOfTagFilter(rows, withIds(NO_IDS, [1]), []).size).toBe(0);
		expect(rowsOutOfTagFilter(rows, NO_IDS, [7]).size).toBe(0);
	});
});
