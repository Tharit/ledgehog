import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './http.js';
import {
	classifyRuleError,
	createRule,
	locationPath,
	deleteRule,
	getRule,
	listRules,
	updateRule,
	type RuleFields
} from './rules.js';

const fetchMock = vi.fn();

function reply(payload: unknown, status = 200): Response {
	return new Response(JSON.stringify(payload), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

function failure(status: number, code: string, details: unknown = null): Response {
	return reply({ error: { code, message: 'x', details } }, status);
}

function last(): [string, RequestInit] {
	return fetchMock.mock.calls.at(-1) as [string, RequestInit];
}

const fields: RuleFields = {
	name: 'Rent',
	sets: 'category',
	category_id: 4,
	conditions: [{ field: 'counterparty_name', op: 'starts_with', value: 'Landlord' }],
	priority: 100
};

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('reading rules', () => {
	it('lists them', async () => {
		fetchMock.mockResolvedValue(reply([{ id: 1 }]));

		expect(await listRules()).toEqual([{ id: 1 }]);
		const [url, init] = last();
		expect(url).toBe('/api/ledger/rules');
		expect(init.method).toBe('GET');
	});

	it('gets one by id', async () => {
		fetchMock.mockResolvedValue(reply({ id: 7 }));

		await getRule(7);

		expect(last()[0]).toBe('/api/ledger/rules/7');
	});
});

describe('createRule', () => {
	it('posts the rule with dry_run in the body and the page in the query', async () => {
		fetchMock.mockResolvedValue(reply({ dry_run: true }));

		await createRule(fields, { dryRun: true, limit: 50 });

		const [url, init] = last();
		expect(url).toBe('/api/ledger/rules?limit=50');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual({
			...fields,
			dry_run: true,
			expected_count: null
		});
	});

	it('carries the previewed count on the real run', async () => {
		fetchMock.mockResolvedValue(reply({ dry_run: false }, 201));

		await createRule(fields, { expectedCount: 12 });

		expect(JSON.parse(last()[1].body as string)).toMatchObject({
			dry_run: false,
			expected_count: 12
		});
		expect(last()[0]).toBe('/api/ledger/rules');
	});

	it('asks for a later page with an offset', async () => {
		fetchMock.mockResolvedValue(reply({}));

		await createRule(fields, { dryRun: true, limit: 50, offset: 50 });

		expect(last()[0]).toBe('/api/ledger/rules?limit=50&offset=50');
	});
});

describe('updateRule', () => {
	it('puts the whole rule to its id', async () => {
		fetchMock.mockResolvedValue(reply({}));

		await updateRule(3, fields, { dryRun: true, limit: 25 });

		const [url, init] = last();
		expect(url).toBe('/api/ledger/rules/3?limit=25');
		expect(init.method).toBe('PUT');
		expect(JSON.parse(init.body as string)).toMatchObject({
			name: 'Rent',
			sets: 'category',
			dry_run: true
		});
	});
});

describe('deleteRule', () => {
	it('previews with dry_run in the query', async () => {
		fetchMock.mockResolvedValue(reply({}));

		await deleteRule(3, { dryRun: true, limit: 1 });

		const [url, init] = last();
		expect(url).toBe('/api/ledger/rules/3?dry_run=true&limit=1');
		expect(init.method).toBe('DELETE');
		expect(init.body).toBeUndefined();
	});

	it('carries the previewed count on the real run', async () => {
		fetchMock.mockResolvedValue(reply({}));

		await deleteRule(3, { expectedCount: 9 });

		expect(last()[0]).toBe('/api/ledger/rules/3?expected_count=9');
	});
});

describe('classifyRuleError', () => {
	async function fail(status: number, code: string, details: unknown = null) {
		fetchMock.mockResolvedValue(failure(status, code, details));
		return classifyRuleError(await createRule(fields).catch((e) => e));
	}

	it('knows a taken name by its reason', async () => {
		expect(await fail(409, 'conflict', { reason: 'duplicate_name' })).toEqual({
			kind: 'duplicate_name'
		});
	});

	it('reads what a moved result was and is', async () => {
		expect(
			await fail(409, 'conflict', { reason: 'filter_result_changed', expected: 3, actual: 5 })
		).toEqual({ kind: 'filter_result_changed', expected: 3, actual: 5 });
	});

	it('names the field of a stale reference', async () => {
		expect(
			await fail(409, 'stale_reference', { field: 'category_id', entity: 'category', id: 4 })
		).toEqual({ kind: 'stale_reference', field: 'category_id', entity: 'category' });
	});

	it('names the field of an invalid rule', async () => {
		expect(
			await fail(422, 'invalid_rule', [
				{ location: ['body', 'purpose_regex'], message: 'bad', type: 'invalid_rule' }
			])
		).toEqual({ kind: 'invalid_rule', field: 'purpose_regex', message: 'bad' });
	});

	it('names the condition and the part of an invalid rule', async () => {
		expect(
			await fail(422, 'invalid_rule', [
				{
					location: ['body', 'conditions[2].value'],
					message: 'conditions[2]: the value must not be blank',
					type: 'invalid_rule'
				}
			])
		).toEqual({
			kind: 'invalid_rule',
			field: 'conditions[2].value',
			message: 'conditions[2]: the value must not be blank'
		});
	});

	it('names the condition of a validation error given as segments', async () => {
		expect(
			await fail(422, 'validation_error', [
				{ location: ['body', 'conditions', 1, 'value'], message: 'too long' },
				{ location: ['body', 'name'], message: 'short' }
			])
		).toEqual({
			kind: 'validation',
			problems: [
				{ field: 'conditions[1].value', message: 'too long' },
				{ field: 'name', message: 'short' }
			]
		});
	});

	it('lists the fields of a validation error', async () => {
		expect(
			await fail(422, 'validation_error', [{ location: ['body', 'name'], message: 'short' }])
		).toEqual({ kind: 'validation', problems: [{ field: 'name', message: 'short' }] });
	});

	it('knows a missing rule, a lost session and a lost network', async () => {
		expect(await fail(404, 'not_found')).toEqual({ kind: 'not_found' });
		expect(await fail(401, 'unauthenticated')).toEqual({ kind: 'unauthenticated' });
		expect(classifyRuleError(new ApiError(0, 'network_error', 'x'))).toEqual({ kind: 'network' });
		expect(classifyRuleError(new TypeError('boom'))).toEqual({ kind: 'network' });
	});

	it('leaves anything else as other, with its status', async () => {
		expect(await fail(500, 'internal')).toEqual({ kind: 'other', status: 500 });
		expect(await fail(409, 'conflict', { reason: 'something_else' })).toEqual({
			kind: 'other',
			status: 409
		});
	});
});

describe('locationPath', () => {
	it('drops the body and writes list positions in brackets', () => {
		expect(locationPath(['body', 'name'])).toBe('name');
		expect(locationPath(['body', 'conditions', 0, 'op'])).toBe('conditions[0].op');
		expect(locationPath(['body', 'conditions[3].field'])).toBe('conditions[3].field');
		expect(locationPath(['body'])).toBe('');
	});
});
