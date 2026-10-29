import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './http.js';
import {
	classifyImporterError,
	createInstance,
	deleteInstance,
	getRun,
	linkAccount,
	listImporters,
	listInstances,
	listRuns,
	resetInstance,
	revertRun,
	unlinkAccount,
	updateInstance,
	uploadFile
} from './importers.js';

const fetchMock = vi.fn();

function reply(payload: unknown, status = 200): Response {
	return new Response(JSON.stringify(payload), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

// a fresh Response for every call: a body can be read once
function answer(payload: unknown, status = 200) {
	fetchMock.mockImplementation(async () => reply(payload, status));
}

function failure(status: number, code: string, details: unknown = null, message = 'x'): Response {
	return reply({ error: { code, message, details } }, status);
}

function last(): [string, RequestInit] {
	return fetchMock.mock.calls.at(-1) as [string, RequestInit];
}

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('the catalog and the instances', () => {
	it('reads the catalog and the instance list', async () => {
		answer([{ name: 'csv' }]);
		expect(await listImporters()).toEqual([{ name: 'csv' }]);
		expect(last()[0]).toBe('/api/importers');

		answer([{ id: 1 }]);
		expect(await listInstances()).toEqual([{ id: 1 }]);
		expect(last()[0]).toBe('/api/importers/instances');
	});

	it('adds an instance without an access (a file importer holds no login)', async () => {
		answer({ id: 4 }, 201);
		await createInstance('csv', { label: 'Giro', settings: { quote: '"' } });
		const [url, init] = last();
		expect(url).toBe('/api/importers/instances');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual({
			importer: 'csv',
			label: 'Giro',
			settings: { quote: '"' }
		});
	});

	it('changes, resets and deletes an instance', async () => {
		answer({ id: 4 });
		await updateInstance(4, { disabled: true });
		expect(last()[0]).toBe('/api/importers/instances/4');
		expect(last()[1].method).toBe('PUT');
		expect(JSON.parse(last()[1].body as string)).toEqual({ disabled: true });

		await resetInstance(4);
		expect(last()[0]).toBe('/api/importers/instances/4/reset');

		answer({ settle: { touched_entry_ids: [], error: null } });
		await deleteInstance(4);
		expect(last()[1].method).toBe('DELETE');
	});
});

describe('links', () => {
	it('previews a link with dry_run and sends no reference', async () => {
		answer({ user_authored_count: 0 });
		await linkAccount(2, 7, { dryRun: true });
		const [url, init] = last();
		expect(url).toBe('/api/importers/instances/2/links');
		expect(JSON.parse(init.body as string)).toEqual({ account_id: 7, dry_run: true });
	});

	it('sends the reference discovery found when there is one', async () => {
		answer({ user_authored_count: 0 });
		await linkAccount(2, 7, { externalRef: 'DE01 0001' });
		expect(JSON.parse(last()[1].body as string)).toEqual({
			account_id: 7,
			dry_run: false,
			external_ref: 'DE01 0001'
		});
	});

	it('unlinks an account', async () => {
		answer({ settle: {} });
		await unlinkAccount(2, 7);
		expect(last()[0]).toBe('/api/importers/instances/2/links/7');
		expect(last()[1].method).toBe('DELETE');
	});
});

describe('uploadFile', () => {
	it('sends the file, the account and the dry-run flag as multipart fields', async () => {
		answer({ run_id: null, dry_run: true });
		const file = new File(['a;b'], 'export.csv', { type: 'text/csv' });
		await uploadFile(3, { file, accountId: 9, dryRun: true });
		const [url, init] = last();
		expect(url).toBe('/api/importers/instances/3/upload');
		const form = init.body as FormData;
		expect(form).toBeInstanceOf(FormData);
		expect((form.get('file') as File).name).toBe('export.csv');
		expect(form.get('account_id')).toBe('9');
		expect(form.get('dry_run')).toBe('true');
		expect(init.headers).not.toHaveProperty('Content-Type');
	});

	it('asks for the real run by default', async () => {
		answer({ run_id: 1, dry_run: false });
		await uploadFile(3, { file: new Blob(['x']), accountId: 9 });
		expect((last()[1].body as FormData).get('dry_run')).toBe('false');
	});
});

describe('runs', () => {
	it('lists runs with the filter as query parameters', async () => {
		answer({ runs: [], total: 0, limit: 20, offset: 0 });
		await listRuns({ accountId: 5, status: 'ok', limit: 20 });
		expect(last()[0]).toBe('/api/importers/runs?account_id=5&status=ok&limit=20');
		await listRuns({ accountId: 5, limit: 100, offset: 200 });
		expect(last()[0]).toBe('/api/importers/runs?account_id=5&limit=100&offset=200');
		await listRuns();
		expect(last()[0]).toBe('/api/importers/runs');
	});

	it('reads one run', async () => {
		answer({ id: 8 });
		expect(await getRun(8)).toEqual({ id: 8 });
		expect(last()[0]).toBe('/api/importers/runs/8');
	});

	it('previews a revert and carries the versions back on the real one', async () => {
		answer({ run_id: 8, versions: { '3': 2 } });
		await revertRun(8, { dryRun: true });
		expect(JSON.parse(last()[1].body as string)).toEqual({
			dry_run: true,
			expected_versions: null
		});
		await revertRun(8, { expectedVersions: { '3': 2 } });
		expect(last()[0]).toBe('/api/importers/runs/8/revert');
		expect(JSON.parse(last()[1].body as string)).toEqual({
			dry_run: false,
			expected_versions: { '3': 2 }
		});
	});
});

describe('classifyImporterError', () => {
	async function classified(response: Response) {
		fetchMock.mockResolvedValue(response);
		try {
			await listInstances();
		} catch (error) {
			return classifyImporterError(error);
		}
		throw new Error('expected a failure');
	}

	it('names the setting of an invalid profile', async () => {
		expect(
			await classified(
				failure(422, 'invalid_profile', { setting: 'amount.column' }, 'amount: give one column')
			)
		).toEqual({
			kind: 'invalid_profile',
			setting: 'amount.column',
			message: 'amount: give one column'
		});
	});

	it('reads the field of a validation error from its location', async () => {
		const out = await classified(
			failure(422, 'validation_error', [{ location: ['body', 'label'], message: 'required' }])
		);
		expect(out).toEqual({
			kind: 'validation',
			problems: [{ field: 'label', message: 'required' }]
		});
	});

	it('keeps the report and the retryability of a failed parse', async () => {
		const out = await classified(
			failure(422, 'parse_failed', { retryable: false, report: { rows_read: 0 } }, 'no header')
		);
		expect(out).toMatchObject({ kind: 'parse_failed', retryable: false, message: 'no header' });
	});

	it('routes the refusals by code', async () => {
		for (const code of [
			'instance_has_runs',
			'account_closed',
			'account_not_linked',
			'file_too_large',
			'already_linked'
		]) {
			expect(await classified(failure(409, code))).toEqual({ kind: code });
		}
		expect(await classified(failure(409, 'conflict', { reason: 'clearance_account' }))).toEqual({
			kind: 'clearance_account'
		});
		expect(
			await classified(failure(422, 'contract_violation', { rule: 'currency_mismatch' }))
		).toMatchObject({
			kind: 'contract_violation',
			rule: 'currency_mismatch'
		});
		expect(await classified(failure(500, 'boom'))).toEqual({ kind: 'other', status: 500 });
	});

	it('treats anything that is not an ApiError as the network', () => {
		expect(classifyImporterError(new Error('x'))).toEqual({ kind: 'network' });
		expect(classifyImporterError(new ApiError(0, 'network_error', 'x'))).toEqual({
			kind: 'network'
		});
	});
});
