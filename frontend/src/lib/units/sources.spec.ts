import { describe, expect, it } from 'vitest';
import {
	activeUnitSource,
	neighbourEntry,
	registerUnitSource,
	type UnitSource
} from './sources.js';

// ids 1,2 are one unit (key 10); 3 is derived (no unit); 4 is key 11; 5,6 are key 12
const rows = [
	{ id: 1, unit_key: 10 },
	{ id: 2, unit_key: 10 },
	{ id: 3, unit_key: null },
	{ id: 4, unit_key: 11 },
	{ id: 5, unit_key: 12 },
	{ id: 6, unit_key: 12 }
];

describe('neighbourEntry', () => {
	it('skips the siblings of the same unit', () => {
		expect(neighbourEntry(rows, 1, 1)).toBe(4);
		expect(neighbourEntry(rows, 2, 1)).toBe(4);
		expect(neighbourEntry(rows, 5, -1)).toBe(4);
	});

	it('skips entries that are in no unit', () => {
		expect(neighbourEntry(rows, 4, -1)).toBe(2);
	});

	it('is null at the ends and for an unknown entry', () => {
		expect(neighbourEntry(rows, 1, -1)).toBeNull();
		expect(neighbourEntry(rows, 6, 1)).toBeNull();
		expect(neighbourEntry(rows, 99, 1)).toBeNull();
	});

	it('steps from a derived row to the next unit', () => {
		expect(neighbourEntry(rows, 3, 1)).toBe(4);
	});
});

describe('the registry', () => {
	const source = (): UnitSource => ({ neighbour: () => null, patch: () => {} });

	it('the newest source is the active one, and a stale one cannot unregister it', () => {
		const a = source();
		const b = source();
		const offA = registerUnitSource(a);
		const offB = registerUnitSource(b);
		expect(activeUnitSource()).toBe(b);
		offA();
		expect(activeUnitSource()).toBe(b);
		offB();
		expect(activeUnitSource()).toBeNull();
	});
});
