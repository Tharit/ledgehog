import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import {
	applyAffected,
	clearMarks,
	insertCreated,
	markOf,
	MARK_CONFIRMED,
	MARK_CONSEQUENCE,
	MARK_DELETED,
	MARK_RESOLVED,
	MARK_RETURNED,
	noMarks
} from './patch.js';

const rows = [entry({ id: 1 }), entry({ id: 2 }), entry({ id: 3 })];

describe('applyAffected', () => {
	it('replaces held rows by id and keeps the order', () => {
		const out = applyAffected(rows, {
			entries: [entry({ id: 3, note: 'x' }), entry({ id: 1, note: 'y' })]
		});
		expect(out.entries.map((e) => [e.id, e.note])).toEqual([
			[1, 'y'],
			[2, null],
			[3, 'x']
		]);
	});

	it('writes the tags a commit changed into the rows', () => {
		const held = [entry({ id: 1, tag_ids: [7] }), entry({ id: 2 })];
		const out = applyAffected(held, { entries: [entry({ id: 1, tag_ids: [7, 8] })] });
		expect(out.entries.map((e) => e.tag_ids)).toEqual([[7, 8], []]);
	});

	it('never adds a row the list does not hold, nor marks it', () => {
		const out = applyAffected(rows, { entries: [entry({ id: 9 })], resolved: [9] });
		expect(out.entries.map((e) => e.id)).toEqual([1, 2, 3]);
		expect(out.marks.resolved.size).toBe(0);
	});

	it('marks resolved rows and rows returned to review', () => {
		const out = applyAffected(rows, {
			entries: [entry({ id: 1 }), entry({ id: 2 })],
			resolved: [1],
			returned_to_review: [2]
		});
		expect(out.marks.resolved.get(1)).toBe(MARK_RESOLVED);
		expect(out.marks.returnedToReview.get(2)).toBe(MARK_RETURNED);
	});

	it('marks a consequence only when the review state changed: refreshed proposals are silent', () => {
		const out = applyAffected(rows, {
			entries: [entry({ id: 2, category_id: 10 }), entry({ id: 3, review_flags: ['unconfirmed'] })]
		});
		expect(out.marks.consequence.has(2)).toBe(false);
		expect(out.marks.consequence.get(3)).toBe(MARK_CONSEQUENCE);
		expect(out.entries[1].category_id).toBe(10);
	});

	it('marks a committed row resolved (muted); only a confirmed one also gets the check', () => {
		const out = applyAffected(rows, {
			entries: [entry({ id: 1 }), entry({ id: 2, review_flags: ['unconfirmed'] })],
			resolved: [1, 2],
			confirmed: [1]
		});
		expect(out.marks.resolved.get(1)).toBe(MARK_RESOLVED);
		expect(out.marks.resolved.get(2)).toBe(MARK_RESOLVED);
		expect(out.marks.confirmed.get(1)).toBe(MARK_CONFIRMED);
		expect(out.marks.confirmed.has(2)).toBe(false);
		// a committed row that stays in review is not also a consequence
		expect(out.marks.consequence.has(2)).toBe(false);
	});

	it('keeps deleted rows, marked', () => {
		const out = applyAffected(rows, { entries: [], removed_entry_ids: [2, 77] });
		expect(out.entries).toHaveLength(3);
		expect(out.marks.deleted.get(2)).toBe(MARK_DELETED);
		expect(out.marks.deleted.has(77)).toBe(false);
	});

	it('adds to the marks it is given', () => {
		const first = applyAffected(rows, { entries: [entry({ id: 1 })], resolved: [1] });
		const second = applyAffected(
			first.entries,
			{ entries: [entry({ id: 2 })], resolved: [2] },
			first.marks
		);
		expect([...second.marks.resolved.keys()]).toEqual([1, 2]);
	});
});

describe('marks', () => {
	const all = () =>
		applyAffected(rows, {
			entries: [entry({ id: 1 }), entry({ id: 2 }), entry({ id: 3 }), entry({ id: 4 })],
			resolved: [1],
			confirmed: [1],
			returned_to_review: [3],
			removed_entry_ids: [3]
		}).marks;

	it('the fading ones fade when the cursor visits the row', () => {
		const marks = {
			...all(),
			consequence: new Map([[2, MARK_CONSEQUENCE]])
		};
		expect(markOf(clearMarks(marks, 2), 2)).toBeUndefined();
		expect(markOf(clearMarks(marks, 3), 3)).toBeUndefined();
		expect(clearMarks(marks, 3).deleted.has(3)).toBe(false);
	});

	it('the resolved and confirmed marks stay when the cursor visits the row (until a refresh)', () => {
		const marks = all();
		expect(clearMarks(marks, 1)).toBe(marks);
		expect(markOf(clearMarks(marks, 1), 1)).toBe(MARK_RESOLVED);
		expect(clearMarks(marks, 1).confirmed.has(1)).toBe(true);
	});

	it('is the same marks when the row has none', () => {
		const marks = noMarks();
		expect(clearMarks(marks, 5)).toBe(marks);
	});
});

describe('insertCreated: the one exception to never adding a row', () => {
	const unitRows = [
		entry({ id: 1, unit_key: 1 }),
		entry({ id: 2, unit_key: 5 }),
		entry({ id: 3, unit_key: 5 }),
		entry({ id: 4, unit_key: 9 })
	];

	it('puts the created entries after the anchor and the rest of its unit, by id', () => {
		const out = insertCreated(
			unitRows,
			[entry({ id: 12, unit_key: 5 }), entry({ id: 11, unit_key: 5 })],
			2
		);
		expect(out.map((e) => e.id)).toEqual([1, 2, 3, 11, 12, 4]);
	});

	it('does not insert an entry the list holds again', () => {
		expect(insertCreated(unitRows, [entry({ id: 3, unit_key: 5 })], 2).map((e) => e.id)).toEqual([
			1, 2, 3, 4
		]);
	});

	it('adds nothing when the list holds neither the anchor nor a row of the unit', () => {
		expect(insertCreated(unitRows, [entry({ id: 20, unit_key: 77 })], 70)).toHaveLength(4);
	});

	it('finds the unit by key when only a sibling of the anchor is held', () => {
		const out = insertCreated([entry({ id: 3, unit_key: 5 })], [entry({ id: 8, unit_key: 5 })], 2);
		expect(out.map((e) => e.id)).toEqual([3, 8]);
	});

	it('is applied by applyAffected for created ids, and the new rows are marked resolved', () => {
		const out = applyAffected(unitRows, {
			entries: [entry({ id: 1, unit_key: 1 }), entry({ id: 11, unit_key: 1 })],
			created: [11],
			resolved: [1, 11],
			anchor_entry_id: 1
		});
		expect(out.entries.map((e) => e.id)).toEqual([1, 11, 2, 3, 4]);
		expect(out.marks.resolved.has(11)).toBe(true);
	});

	it('inserts nothing without an anchor', () => {
		const out = applyAffected(unitRows, { entries: [entry({ id: 11 })], created: [11] });
		expect(out.entries).toHaveLength(4);
	});
});
