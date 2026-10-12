import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './http.js';
import { applyBody, applyTag, createTag, tagEntry, untagEntry } from './tags.js';
import type { EntryFilter } from './types.js';

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

const empty: EntryFilter = {
	account_id: [],
	category_id: [],
	category_descendants: true,
	uncategorised: false,
	payee_id: [],
	tag_id: [],
	q: '',
	type: [],
	flag: []
};

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('applyBody', () => {
	it('uses the names of the list parameters and the controls', () => {
		const body = applyBody(
			{
				...empty,
				from: '2026-10-01',
				account_id: [2],
				tag_id: [7],
				q: '  rewe ',
				amount_min: 100,
				currency: 'EUR',
				direction: 'out',
				type: ['flow'],
				flag: ['waiting'],
				category_descendants: false
			},
			{ dryRun: true, expectedCount: 12 }
		);

		expect(body).toMatchObject({
			from: '2026-10-01',
			to: null,
			account_id: [2],
			tag_id: [7],
			q: 'rewe',
			amount_min: 100,
			amount_max: null,
			currency: 'EUR',
			direction: 'out',
			type: ['flow'],
			flag: ['waiting'],
			category_descendants: false,
			all: false,
			dry_run: true,
			expected_count: 12
		});
	});

	it('never sets `all` unless asked, and sends no count by default', () => {
		const body = applyBody({ ...empty, q: '   ' });
		expect(body.all).toBe(false);
		expect(body.dry_run).toBe(false);
		expect(body.expected_count).toBeNull();
		expect(body.q).toBeNull();
	});
});

describe('applyTag', () => {
	it('posts the body to the tag and returns the answer', async () => {
		const out = { dry_run: true, newly_tagged: 3, entries: [] };
		fetchMock.mockResolvedValue(reply(out));

		const result = await applyTag(5, applyBody(empty, { dryRun: true }));

		expect(result).toEqual(out);
		const [url, init] = last();
		expect(url).toBe('/api/ledger/tags/5/apply');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toMatchObject({ dry_run: true, all: false });
	});

	it('reports a changed result with what it was and is', async () => {
		fetchMock.mockResolvedValue(
			failure(409, 'conflict', { reason: 'filter_result_changed', expected: 3, actual: 5 })
		);

		const error = await applyTag(5, applyBody(empty)).catch((e) => e);

		expect(error).toBeInstanceOf(ApiError);
		expect(error).toMatchObject({ status: 409, code: 'conflict' });
		expect(error.details).toEqual({ reason: 'filter_result_changed', expected: 3, actual: 5 });
	});

	it('reports an empty filter as a validation error', async () => {
		fetchMock.mockResolvedValue(
			failure(422, 'validation_error', [{ location: ['body', 'all'], message: 'x' }])
		);

		const error = await applyTag(5, applyBody(empty)).catch((e) => e);

		expect(error).toMatchObject({ status: 422, code: 'validation_error' });
	});

	it('reports a missing tag', async () => {
		fetchMock.mockResolvedValue(failure(404, 'not_found'));

		await expect(applyTag(5, applyBody(empty))).rejects.toMatchObject({ status: 404 });
	});
});

describe('createTag', () => {
	it('posts the name with no colour', async () => {
		fetchMock.mockResolvedValue(
			reply({ tag: { id: 9, name: 'Holiday', color: null }, settle: {} }, 201)
		);

		const out = await createTag('Holiday');

		expect(out.tag.id).toBe(9);
		const [url, init] = last();
		expect(url).toBe('/api/ledger/tags');
		expect(JSON.parse(init.body as string)).toEqual({ name: 'Holiday', color: null });
	});

	it('reports a duplicate name', async () => {
		fetchMock.mockResolvedValue(failure(409, 'conflict', { reason: 'duplicate_name' }));

		await expect(createTag('Holiday')).rejects.toMatchObject({
			code: 'conflict',
			details: { reason: 'duplicate_name' }
		});
	});
});

describe('tagEntry and untagEntry', () => {
	it('PUT adds and DELETE removes, answering the tag ids now', async () => {
		fetchMock.mockImplementation(async () =>
			reply({ entry: { id: 4, tag_ids: [7] }, changed: true, settle: { error: null } })
		);

		const added = await tagEntry(4, 7);
		expect(last()[0]).toBe('/api/ledger/entries/4/tags/7');
		expect(last()[1].method).toBe('PUT');
		expect(added.entry.tag_ids).toEqual([7]);

		await untagEntry(4, 7);
		expect(last()[1].method).toBe('DELETE');
	});

	it('reports a derived entry and a vanished entry', async () => {
		fetchMock.mockResolvedValueOnce(failure(409, 'conflict', { reason: 'derived_entry' }));
		await expect(tagEntry(4, 7)).rejects.toMatchObject({
			code: 'conflict',
			details: { reason: 'derived_entry' }
		});

		fetchMock.mockResolvedValueOnce(failure(404, 'not_found'));
		await expect(untagEntry(4, 7)).rejects.toMatchObject({ status: 404 });
	});
});
