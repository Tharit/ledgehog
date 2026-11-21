import { describe, expect, it } from 'vitest';
import { byMonthAndDay, cutBy } from './cuts.js';

type Item = { id: number; on: string; payee?: string };
const item = (id: number, on: string, payee?: string): Item => ({ id, on, payee });
const ids = (items: Item[]) => items.map((i) => i.id);

describe('cutBy', () => {
	it('cuts one level: a band per run of one key, in order', () => {
		const bands = cutBy(
			[item(1, '', 'REWE'), item(2, '', 'REWE'), item(3, '', 'Aldi')],
			[{ key: (i) => i.payee ?? '', label: (i) => i.payee ?? '' }]
		);

		expect(bands.map((b) => [b.label, ids(b.items)])).toEqual([
			['REWE', [1, 2]],
			['Aldi', [3]]
		]);
		expect(bands.every((b) => b.bands.length === 0)).toBe(true);
	});

	it('starts a new band when a key comes back, never reordering', () => {
		const bands = cutBy(
			[item(1, '', 'A'), item(2, '', 'B'), item(3, '', 'A')],
			[{ key: (i) => i.payee ?? '', label: (i) => `by ${i.payee}` }]
		);

		expect(bands.map((b) => ids(b.items))).toEqual([[1], [2], [3]]);
		expect(new Set(bands.map((b) => b.key)).size).toBe(2);
	});

	it('returns nothing for nothing', () => {
		expect(cutBy([], [{ key: () => 'x', label: () => 'x' }])).toEqual([]);
	});
});

describe('byMonthAndDay', () => {
	const cuts = byMonthAndDay<Item>(
		(i) => i.on,
		(date) => `month ${date.slice(0, 7)}`,
		(date) => `day ${date}`
	);

	it('nests days within months', () => {
		const bands = cutBy(
			[
				item(1, '2026-11-17'),
				item(2, '2026-11-17'),
				item(3, '2026-11-02'),
				item(4, '2026-10-30'),
				item(5, '2026-10-30')
			],
			cuts
		);

		expect(bands.map((b) => b.label)).toEqual(['month 2026-11', 'month 2026-10']);
		expect(bands[0].items).toEqual([]);
		expect(bands[0].bands.map((d) => [d.label, ids(d.items)])).toEqual([
			['day 2026-11-17', [1, 2]],
			['day 2026-11-02', [3]]
		]);
		expect(bands[1].bands.map((d) => [d.label, ids(d.items)])).toEqual([
			['day 2026-10-30', [4, 5]]
		]);
	});

	it('keeps every key unique across the result', () => {
		const bands = cutBy([item(1, '2026-11-17'), item(2, '2026-10-17')], cuts);
		const keys = bands.flatMap((m) => [m.key, ...m.bands.map((d) => d.key)]);

		expect(new Set(keys).size).toBe(keys.length);
	});

	it('reads through in the order given', () => {
		const input = [item(1, '2026-11-17'), item(2, '2026-11-16'), item(3, '2026-10-01')];
		const bands = cutBy(input, cuts);

		expect(bands.flatMap((m) => m.bands.flatMap((d) => ids(d.items)))).toEqual([1, 2, 3]);
	});
});
