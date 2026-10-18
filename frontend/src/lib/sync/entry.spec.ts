import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/http.js';
import {
	isBusyRefusal,
	refusalOf,
	refusalText,
	startOrReview,
	SYNC_RUNNING_TEXT,
	type EntryDeps
} from './entry.js';
import { planInstance } from './fixtures.js';

function deps(over: Partial<EntryDeps> = {}) {
	const d = {
		readPlan: vi.fn(async () => [planInstance()]),
		start: vi.fn(async () => null),
		go: vi.fn(async () => {}),
		...over
	};
	return d as typeof d & EntryDeps;
}

const editable = planInstance({
	accounts: [
		{
			account_id: 7,
			external_ref: 'r',
			since: '2026-01-01',
			since_source: 'importer_default',
			editable: true
		}
	]
});

describe('startOrReview', () => {
	it('starts an account with coverage at once and opens the sync page', async () => {
		const d = deps();
		expect(await startOrReview({ instanceId: 1, accountId: 7 }, d)).toBeNull();
		expect(d.start).toHaveBeenCalledWith([{ instance_id: 1, account_id: 7 }]);
		expect(d.go).toHaveBeenCalledWith('/sync');
	});

	it('opens the plan narrowed to an account without coverage, and starts nothing', async () => {
		const d = deps({ readPlan: vi.fn(async () => [editable]) });
		expect(await startOrReview({ instanceId: 1, accountId: 7 }, d)).toBeNull();
		expect(d.start).not.toHaveBeenCalled();
		expect(d.go).toHaveBeenCalledWith('/sync?instance=1&account=7');
	});

	it('starts the documents of a login at once, without reading the plan', async () => {
		const d = deps();
		await startOrReview({ instanceId: 1, accountId: null }, d);
		expect(d.readPlan).not.toHaveBeenCalled();
		expect(d.start).toHaveBeenCalledWith([{ instance_id: 1, kind: 'documents' }]);
	});

	it('returns a refused start and stays where it is', async () => {
		const refusal = { code: 'task_active', message: 'busy' };
		const d = deps({ start: vi.fn(async () => refusal) });
		expect(await startOrReview({ instanceId: 1, accountId: 7 }, d)).toEqual(refusal);
		expect(d.go).not.toHaveBeenCalled();
	});

	it('returns a plan that could not be read', async () => {
		const d = deps({
			readPlan: vi.fn(async () => {
				throw new ApiError(0, 'network_error', 'The server could not be reached.');
			})
		});
		expect(await startOrReview({ instanceId: 1, accountId: 7 }, d)).toMatchObject({
			code: 'network_error'
		});
		expect(d.start).not.toHaveBeenCalled();
	});
});

describe('refusals', () => {
	it('keeps the code of an API error and calls anything else a network error', () => {
		expect(refusalOf(new ApiError(409, 'instance_busy', 'held'))).toEqual({
			code: 'instance_busy',
			message: 'held'
		});
		expect(refusalOf(new Error('x')).code).toBe('network_error');
	});

	it('knows a busy refusal and says it in its own words', () => {
		expect(isBusyRefusal({ code: 'task_active', message: '' })).toBe(true);
		expect(isBusyRefusal({ code: 'instance_busy', message: '' })).toBe(true);
		expect(isBusyRefusal({ code: 'nothing_to_sync', message: '' })).toBe(false);
		expect(refusalText({ code: 'task_active', message: 'x' })).toBe(SYNC_RUNNING_TEXT);
		expect(refusalText({ code: 'nothing_to_sync', message: 'Nothing to sync.' })).toBe(
			'Nothing to sync.'
		);
	});
});
