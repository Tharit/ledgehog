// The duplicate flow against a stand-in for the server's rules (app/core/ingest/duplicates.py),
// at the level of `fetch`, so the request bodies the API layer builds are what is judged: a map of
// `expected_versions` is the versions the caller read, and any written entry it lacks is a 409.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { DuplicateFlow } from './duplicate-flow.svelte.js';
import { provenance, sourceRow } from './fixtures.js';

const fetchMock = vi.fn();

function reply(payload: unknown, status = 200): Response {
	return new Response(JSON.stringify(payload), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

/** entries each source row owns, and their current versions */
const owned: Record<number, number[]> = { 5: [10], 3: [20] };
let versionOf: Record<number, number> = { 10: 4, 20: 7 };

function server(url: string, init: RequestInit): Response {
	if (url.startsWith('/api/ledger/accounts/1/statement'))
		return reply({
			items: [
				sourceRow({ id: 5, booked_on: '2026-10-10' }),
				sourceRow({ id: 3, booked_on: '2026-10-08' })
			],
			total: 2,
			limit: 500,
			offset: 0
		});
	const entryMatch = /^\/api\/ledger\/entries\/(\d+)/.exec(url);
	if (entryMatch) return reply(entry({ id: Number(entryMatch[1]) }));
	const mark = /^\/api\/ledger\/sources\/(\d+)\/duplicate$/.exec(url);
	if (mark) {
		const body = JSON.parse(init.body as string) as {
			of: number;
			dry_run: boolean;
			expected_versions: Record<string, number> | null;
		};
		const removed = owned[Number(mark[1])];
		if (body.expected_versions !== null) {
			const supplied = body.expected_versions;
			const stale = removed.filter((id) => supplied[id] !== versionOf[id]);
			if (stale.length > 0)
				return reply(
					{ error: { code: 'conflict', message: 'x', details: { entry_ids: stale } } },
					409
				);
		}
		return reply({
			dry_run: body.dry_run,
			source_transaction_id: Number(mark[1]),
			of: body.of,
			removed_entry_ids: removed,
			partner_entry_ids: [],
			partners: [],
			freed_document_ids: [],
			repointed_source_ids: [],
			derived_changes: [],
			units: [],
			settle: null,
			versions: removed.map((id) => ({ entry_id: id, version: versionOf[id] }))
		});
	}
	return reply({}, 404);
}

beforeEach(() => {
	versionOf = { 10: 4, 20: 7 };
	fetchMock.mockReset();
	fetchMock.mockImplementation(async (url: string, init: RequestInit) => server(url, init));
	vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const row = provenance({ id: 5, account_id: 1, booked_on: '2026-10-10' });

describe('DuplicateFlow against the server rules', () => {
	it('previews both directions without a conflict, so Mark as duplicate can be pressed', async () => {
		const flow = new DuplicateFlow();
		await flow.start(row);

		await flow.pick(3);

		expect(flow.previews?.this.status).toBe('ready');
		expect(flow.previews?.other.status).toBe('ready');
		expect(flow.canConfirm).toBe(true);
		const dry = fetchMock.mock.calls
			.filter(([url]) => String(url).endsWith('/duplicate'))
			.map(([, init]) => JSON.parse(init.body as string));
		expect(dry).toHaveLength(2);
		expect(dry.every((b) => b.dry_run && b.expected_versions === null)).toBe(true);
	});

	it('marks right after the preview, carrying the versions of the chosen direction', async () => {
		const flow = new DuplicateFlow();
		await flow.start(row);
		await flow.pick(3); // this row is the newer one: it is marked, as the duplicate of row 3

		const result = await flow.confirm();

		expect(result).toMatchObject({ marked: 5, of: 3 });
		const real = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/duplicate')).at(-1)!;
		expect(real[0]).toBe('/api/ledger/sources/5/duplicate');
		expect(JSON.parse(real[1].body as string)).toEqual({
			of: 3,
			dry_run: false,
			expected_versions: { '10': 4 }
		});
	});

	it('when an entry was edited since the preview says so, previews again and can mark then', async () => {
		const flow = new DuplicateFlow();
		await flow.start(row);
		await flow.pick(3);
		versionOf = { ...versionOf, 10: 5 }; // edited elsewhere after the preview

		expect(await flow.confirm()).toBeNull();

		expect(flow.failure?.kind).toBe('conflict');
		expect(flow.failure?.text).toBe(
			'The entries this would change were edited since the preview. The preview is updated: check it and try again.'
		);
		expect(flow.pickedId).toBe(3); // the original stays picked
		expect(flow.canConfirm).toBe(true);
		expect(await flow.confirm()).toMatchObject({ marked: 5, of: 3 });
	});
});
