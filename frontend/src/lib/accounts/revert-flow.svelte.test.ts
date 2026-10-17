import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getEntry, revertRun, type ImportRun } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
import { RevertFlow } from './revert-flow.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	revertRun: vi.fn(),
	getEntry: vi.fn()
}));

const run = {
	id: 5,
	account_id: 1,
	stats: { inserted: 2 },
	revertible: true
} as unknown as ImportRun;

function result(over: Record<string, unknown> = {}) {
	return {
		run_id: 5,
		removed_entry_ids: [10, 11],
		partner_entry_ids: [20],
		freed_document_ids: [],
		repointed_source_ids: [],
		cleared_duplicate_ids: [],
		derived_changes: [],
		versions: { '10': 2, '11': 1, '20': 4 },
		settle: null,
		...over
	};
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => vi.resetAllMocks());

describe('RevertFlow', () => {
	it('previews with a dry run and counts the confirmed entries among those removed', async () => {
		vi.mocked(revertRun).mockResolvedValue(result() as never);
		vi.mocked(getEntry).mockImplementation(async (id) =>
			entry({ id, review_flags: id === 10 ? [] : ['unconfirmed'] })
		);
		const flow = new RevertFlow();

		flow.start(run);
		await flush();

		expect(vi.mocked(revertRun).mock.calls[0]).toEqual([
			5,
			expect.objectContaining({ dryRun: true })
		]);
		expect(flow.status).toBe('ready');
		expect(flow.confirmed).toBe(1);
		expect(flow.canRevert).toBe(true);
	});

	it('does not count confirmed entries when too many were removed to read', async () => {
		const many = Array.from({ length: 51 }, (_, i) => i + 1);
		vi.mocked(revertRun).mockResolvedValue(result({ removed_entry_ids: many }) as never);
		const flow = new RevertFlow();

		flow.start(run);
		await flush();

		expect(getEntry).not.toHaveBeenCalled();
		expect(flow.confirmed).toBeNull();
		expect(flow.status).toBe('ready');
	});

	it('reverts with the versions of the preview', async () => {
		vi.mocked(revertRun).mockResolvedValueOnce(result() as never);
		vi.mocked(getEntry).mockResolvedValue(entry({ id: 10 }));
		const flow = new RevertFlow();
		flow.start(run);
		await flush();
		vi.mocked(revertRun).mockResolvedValueOnce(
			result({ settle: { error: null, touched_entry_ids: [] } }) as never
		);

		const done = await flow.confirm();

		expect(done).not.toBeNull();
		expect(vi.mocked(revertRun).mock.calls[1][1]).toEqual({
			expectedVersions: { '10': 2, '11': 1, '20': 4 }
		});
	});

	it('on a conflict checks again and asks again', async () => {
		vi.mocked(revertRun).mockResolvedValueOnce(result() as never);
		vi.mocked(getEntry).mockResolvedValue(entry({ id: 10 }));
		const flow = new RevertFlow();
		flow.start(run);
		await flush();
		vi.mocked(revertRun).mockRejectedValueOnce(
			new ApiError(409, 'conflict', 'x', { entry_ids: [10] })
		);
		vi.mocked(revertRun).mockResolvedValueOnce(result({ versions: { '10': 3 } }) as never);

		expect(await flow.confirm()).toBeNull();

		expect(flow.failure?.kind).toBe('conflict');
		expect(flow.status).toBe('ready');
		expect(flow.preview?.versions).toEqual({ '10': 3 });
	});

	it('says a run that is no longer the latest cannot be reverted', async () => {
		vi.mocked(revertRun).mockResolvedValueOnce(result() as never);
		vi.mocked(getEntry).mockResolvedValue(entry({ id: 10 }));
		const flow = new RevertFlow();
		flow.start(run);
		await flush();
		vi.mocked(revertRun).mockRejectedValueOnce(
			new ApiError(409, 'not_latest_run', 'x', { newer_run_id: 6 })
		);

		expect(await flow.confirm()).toBeNull();

		expect(flow.failure?.text).toMatch(/latest successful run/);
	});

	it('shows the error when the preview fails', async () => {
		vi.mocked(revertRun).mockRejectedValue(new ApiError(0, 'network_error', 'x'));
		const flow = new RevertFlow();
		flow.start(run);
		await flush();
		expect(flow.status).toBe('error');
		expect(flow.canRevert).toBe(false);
	});
});
