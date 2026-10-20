import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './http.js';
import { getBalances, getByCategory, getOverTime, getOverview } from './reports.js';

const fetchMock = vi.fn();

function reply(payload: unknown, status = 200): Response {
	return new Response(JSON.stringify(payload), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

function lastUrl(): string {
	return (fetchMock.mock.calls.at(-1) as [string])[0];
}

beforeEach(() => {
	fetchMock.mockReset();
	fetchMock.mockImplementation(async () => reply({}));
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('getOverview', () => {
	it('reads the Overview, which takes no parameter', async () => {
		fetchMock.mockImplementation(async () => reply({ as_of: '2026-10-20' }));
		expect(await getOverview()).toEqual({ as_of: '2026-10-20' });
		expect(lastUrl()).toBe('/api/reports/overview');
	});

	it('answers a failure with its code', async () => {
		fetchMock.mockImplementation(async () =>
			reply({ error: { code: 'internal_error', message: 'x', details: null } }, 500)
		);
		await expect(getOverview()).rejects.toBeInstanceOf(ApiError);
	});
});

describe('getOverTime', () => {
	it('asks for a range, and the step, mode, kind and filters when given', async () => {
		await getOverTime({ from: '2026-01-01', to: '2026-06-30' });
		expect(lastUrl()).toBe('/api/reports/over-time?from=2026-01-01&to=2026-06-30');

		await getOverTime({
			from: '2026-01-01',
			to: '2026-06-30',
			step: 'quarter',
			mode: 'category',
			kind: 'income',
			accountIds: [3],
			tagIds: [7]
		});
		expect(lastUrl()).toBe(
			'/api/reports/over-time?from=2026-01-01&to=2026-06-30&step=quarter&mode=category&kind=income&account_id=3&tag_id=7'
		);
	});
});

describe('getBalances', () => {
	it('asks for a range and nothing else', async () => {
		await getBalances('2026-01-01', '2026-06-30');
		expect(lastUrl()).toBe('/api/reports/balances?from=2026-01-01&to=2026-06-30');
	});
});

describe('getByCategory', () => {
	it('asks for a range', async () => {
		await getByCategory({ from: '2026-10-01', to: '2026-10-20' });
		expect(lastUrl()).toBe('/api/reports/by-category?from=2026-10-01&to=2026-10-20');
	});

	it('carries the kind, the filters and `top` when given', async () => {
		await getByCategory({
			from: '2026-10-01',
			to: '2026-10-20',
			kind: 'expense',
			accountIds: [1, 2],
			tagIds: [4],
			top: 5
		});
		expect(lastUrl()).toBe(
			'/api/reports/by-category?from=2026-10-01&to=2026-10-20&kind=expense&account_id=1&account_id=2&tag_id=4&top=5'
		);
	});
});
