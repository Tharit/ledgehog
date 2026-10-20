import { describe, expect, it } from 'vitest';
import { defaultRange, parseParams, sharedQuery, toQuery } from './params.js';

const TODAY = '2026-10-20';

describe('defaultRange', () => {
	it('opens the split on this month and the trends on the last 12 months', () => {
		expect(defaultRange('by-category', TODAY)).toEqual({ from: '2026-10-01', to: '2026-10-31' });
		expect(defaultRange('over-time', TODAY)).toEqual({ from: '2025-10-01', to: '2026-09-30' });
		expect(defaultRange('balances', TODAY)).toEqual({ from: '2025-10-01', to: '2026-09-30' });
	});
});

describe('parseParams', () => {
	it('is the defaults for an empty address', () => {
		expect(parseParams('', 'by-category', TODAY)).toEqual({
			from: '2026-10-01',
			to: '2026-10-31',
			kind: 'expense',
			step: 'month',
			mode: 'income-expense',
			accountIds: [],
			tagIds: []
		});
	});

	it('reads the period, the filters and the report controls', () => {
		const p = parseParams(
			'from=2026-01-01&to=2026-06-30&account_id=3&account_id=2&tag_id=7&kind=income&step=quarter&mode=category',
			'over-time',
			TODAY
		);
		expect(p).toMatchObject({
			from: '2026-01-01',
			to: '2026-06-30',
			accountIds: [2, 3],
			tagIds: [7],
			kind: 'income',
			step: 'quarter',
			mode: 'category'
		});
	});

	it('ignores what it cannot understand', () => {
		const p = parseParams('from=nope&kind=x&step=week&mode=y&account_id=-1', 'over-time', TODAY);
		expect(p).toMatchObject({
			from: '2025-10-01',
			kind: 'expense',
			step: 'month',
			mode: 'income-expense',
			accountIds: []
		});
	});

	it('takes the other end of the default for a range with one end', () => {
		expect(parseParams('from=2026-10-10', 'by-category', TODAY)).toMatchObject({
			from: '2026-10-10',
			to: '2026-10-31'
		});
	});
});

describe('toQuery', () => {
	const back = (report: 'by-category' | 'over-time' | 'balances', search: string) =>
		toQuery(parseParams(search, report, TODAY), report, TODAY).toString();

	it('leaves the defaults out', () => {
		expect(back('by-category', '')).toBe('');
		expect(back('over-time', 'step=month&mode=income-expense')).toBe('');
	});

	it('writes the period, filters and controls canonically', () => {
		expect(
			back(
				'over-time',
				'tag_id=7&account_id=3&account_id=2&step=year&mode=category&kind=income&to=2026-06-30&from=2026-01-01'
			)
		).toBe(
			'from=2026-01-01&to=2026-06-30&account_id=2&account_id=3&tag_id=7&kind=income&step=year&mode=category'
		);
	});

	it('keeps the kind only where the report has one', () => {
		expect(back('over-time', 'kind=income')).toBe('');
		expect(back('by-category', 'kind=income')).toBe('kind=income');
	});

	it('Balances has the period only', () => {
		expect(back('balances', 'account_id=2&kind=income&from=2026-01-01&to=2026-02-01')).toBe(
			'from=2026-01-01&to=2026-02-01'
		);
	});
});

describe('sharedQuery', () => {
	it('carries the period and the filters between tabs, not the report controls', () => {
		expect(sharedQuery('from=2026-01-01&to=2026-02-01&kind=income&step=year&tag_id=4')).toBe(
			'from=2026-01-01&to=2026-02-01&tag_id=4'
		);
		expect(sharedQuery('')).toBe('');
	});
});
