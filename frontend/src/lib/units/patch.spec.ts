import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import {
	applyAffected,
	clearMarks,
	markOf,
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
	it('fade when the cursor visits the row', () => {
		const { marks } = applyAffected(rows, { entries: [entry({ id: 1 })], resolved: [1] });
		expect(markOf(marks, 1)).toBe(MARK_RESOLVED);
		expect(markOf(clearMarks(marks, 1), 1)).toBeUndefined();
		expect(clearMarks(noMarks(), 5).resolved.size).toBe(0);
	});
});
