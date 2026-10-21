import { describe, expect, it } from 'vitest';
import { foldedRows, toggled } from './fold.js';

const row = (key: string, depth: number, hasChildren = false) => ({ key, depth, hasChildren });
const ROWS = [
	row('a', 0, true),
	row('a-itself', 1),
	row('a1', 1, true),
	row('a1x', 2),
	row('b', 0),
	row('c', 0, true),
	row('c1', 1)
];

describe('foldedRows', () => {
	it('shows only the top level when nothing is expanded', () => {
		expect(foldedRows(ROWS, new Set()).map((r) => r.key)).toEqual(['a', 'b', 'c']);
	});

	it('shows the children of an expanded group, and those of a collapsed one not', () => {
		expect(foldedRows(ROWS, new Set(['a'])).map((r) => r.key)).toEqual([
			'a',
			'a-itself',
			'a1',
			'b',
			'c'
		]);
		expect(foldedRows(ROWS, new Set(['a', 'a1', 'c'])).map((r) => r.key)).toEqual([
			'a',
			'a-itself',
			'a1',
			'a1x',
			'b',
			'c',
			'c1'
		]);
	});

	it('hides what is under a collapsed group even when it was expanded itself', () => {
		expect(foldedRows(ROWS, new Set(['a1'])).map((r) => r.key)).toEqual(['a', 'b', 'c']);
	});

	it('marks which rows are expanded; a row without children never is', () => {
		const shown = foldedRows(ROWS, new Set(['a', 'b']));
		expect(shown.map((r) => [r.key, r.expanded]).filter(([, open]) => open)).toEqual([['a', true]]);
	});
});

describe('toggled', () => {
	it('adds a key that is not in and removes one that is', () => {
		expect([...toggled(new Set(['a']), 'b')]).toEqual(['a', 'b']);
		expect([...toggled(new Set(['a', 'b']), 'a')]).toEqual(['b']);
	});
});
