import { describe, expect, it } from 'vitest';
import { datePresets } from './presets.js';

function byId(today: string) {
	return Object.fromEntries(datePresets(today).map((p) => [p.id, [p.from, p.to]]));
}

describe('datePresets', () => {
	it('names the four presets', () => {
		expect(datePresets('2026-10-11').map((p) => p.label)).toEqual([
			'This month',
			'Last month',
			'Last 30 days',
			'This year'
		]);
	});

	it('computes them from today, both ends inclusive', () => {
		expect(byId('2026-10-11')).toEqual({
			'this-month': ['2026-10-01', '2026-10-31'],
			'last-month': ['2026-09-01', '2026-09-30'],
			'last-30-days': ['2026-09-12', '2026-10-11'],
			'this-year': ['2026-01-01', '2026-12-31']
		});
	});

	it('crosses a year boundary for last month', () => {
		const presets = byId('2026-01-15');
		expect(presets['last-month']).toEqual(['2025-12-01', '2025-12-31']);
		expect(presets['last-30-days']).toEqual(['2025-12-17', '2026-01-15']);
	});

	it('knows month lengths, leap years included', () => {
		expect(byId('2028-03-10')['last-month']).toEqual(['2028-02-01', '2028-02-29']);
		expect(byId('2026-03-10')['last-month']).toEqual(['2026-02-01', '2026-02-28']);
		expect(byId('2026-02-10')['this-month']).toEqual(['2026-02-01', '2026-02-28']);
		expect(byId('2026-12-31')['this-month']).toEqual(['2026-12-01', '2026-12-31']);
	});

	it('last 30 days is thirty days counting today', () => {
		expect(byId('2026-03-30')['last-30-days']).toEqual(['2026-03-01', '2026-03-30']);
	});
});
