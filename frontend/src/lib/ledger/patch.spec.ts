import { describe, expect, it } from 'vitest';
import { entry } from './fixtures.js';
import {
	CHANGED_BY_YOU,
	CHANGED_ELSEWHERE,
	mergeRefreshed,
	NO_IDS,
	patchTagIds,
	rowsOutOfTagFilter,
	withIds
} from './patch.js';

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

describe('mergeRefreshed', () => {
	const held = new Set([3, 2, 1]);

	it('replaces held rows by the fresh ones, in the same order', () => {
		const fresh = [entry({ id: 1, version: 5, tag_ids: [9] }), entry({ id: 3, version: 2 })];

		const out = mergeRefreshed(rows, fresh, held);

		expect(out.entries.map((e) => e.id)).toEqual([3, 2, 1]);
		expect(out.entries[0]).toBe(fresh[1]);
		expect(out.entries[2].tag_ids).toEqual([9]);
		expect(out.entries[2].version).toBe(5);
	});

	it('keeps held rows the answer lacks and names them, without adding new rows', () => {
		const out = mergeRefreshed(rows, [entry({ id: 3 }), entry({ id: 50 })], held);

		expect(out.entries.map((e) => e.id)).toEqual([3, 2, 1]);
		expect(out.entries[1]).toBe(rows[1]);
		expect([...out.missing]).toEqual([2, 1]);
	});

	it('does not count a row that was not held when the request was made', () => {
		expect(mergeRefreshed(rows, [], new Set([3])).missing.has(2)).toBe(false);
	});
});

describe('mark tooltips', () => {
	it("tells the user's own change from one made elsewhere", () => {
		expect(CHANGED_BY_YOU).toBe('changed by your last action');
		expect(CHANGED_ELSEWHERE).toBe('no longer matches, or changed elsewhere');
	});
});
