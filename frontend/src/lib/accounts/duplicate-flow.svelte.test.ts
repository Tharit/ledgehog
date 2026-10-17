import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getEntry, getStatement, markDuplicate } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
import { DuplicateFlow } from './duplicate-flow.svelte.js';
import { provenance, sourceRow } from './fixtures.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	getStatement: vi.fn(),
	getEntry: vi.fn(),
	markDuplicate: vi.fn()
}));

function out(over: Record<string, unknown> = {}) {
	return {
		dry_run: true,
		source_transaction_id: 0,
		of: 0,
		removed_entry_ids: [10],
		partner_entry_ids: [],
		partners: [],
		freed_document_ids: [],
		repointed_source_ids: [],
		derived_changes: [],
		units: [],
		settle: null,
		versions: [{ entry_id: 10, version: 3 }],
		...over
	};
}

const row = provenance({ id: 5, booked_on: '2026-10-10' });

async function started() {
	vi.mocked(getStatement).mockResolvedValue({
		items: [
			sourceRow({ id: 5, booked_on: '2026-10-10' }),
			sourceRow({ id: 3, booked_on: '2026-10-08' }),
			sourceRow({ id: 9, booked_on: '2026-10-13' })
		],
		total: 3,
		limit: 500,
		offset: 0
	});
	vi.mocked(getEntry).mockResolvedValue(entry({ id: 10 }));
	const flow = new DuplicateFlow();
	await flow.start(row);
	return flow;
}

beforeEach(() => vi.resetAllMocks());

describe('DuplicateFlow', () => {
	it('asks the statement for the rows of the same amount and lists them, nearest date first, without itself', async () => {
		const flow = await started();

		expect(vi.mocked(getStatement).mock.calls[0]).toEqual([
			row.account_id,
			expect.objectContaining({ amount: -4000, limit: 500 })
		]);
		expect(flow.candidatesStatus).toBe('ready');
		expect(flow.candidates.map((c) => c.id)).toEqual([3, 9]);
	});

	it('previews both directions on a pick, the newer row preselected as the duplicate', async () => {
		const flow = await started();
		vi.mocked(markDuplicate).mockResolvedValue(out() as never);

		await flow.pick(3); // the other row is older: this row is the newer

		expect(flow.direction).toBe('this');
		expect(vi.mocked(markDuplicate).mock.calls.map((c) => [c[0], c[1], c[2]?.dryRun])).toEqual([
			[5, 3, true],
			[3, 5, true]
		]);
		expect(flow.previews?.this.status).toBe('ready');
		expect(flow.previews?.other.status).toBe('ready');
		expect(flow.canConfirm).toBe(true);
	});

	it('preselects the other row when it is the newer one', async () => {
		const flow = await started();
		vi.mocked(markDuplicate).mockResolvedValue(out() as never);

		await flow.pick(9);

		expect(flow.direction).toBe('other');
	});

	it('marks the chosen direction with the versions of its own preview', async () => {
		const flow = await started();
		vi.mocked(markDuplicate).mockImplementation(async (mark, _of, options) =>
			options?.dryRun
				? (out({
						versions: [{ entry_id: mark === 5 ? 10 : 20, version: mark === 5 ? 3 : 7 }]
					}) as never)
				: (out({ dry_run: false }) as never)
		);
		await flow.pick(3);
		flow.choose('other');

		const result = await flow.confirm();

		const real = vi.mocked(markDuplicate).mock.calls.at(-1)!;
		expect([real[0], real[1], real[2]?.dryRun ?? false]).toEqual([3, 5, false]);
		expect(real[2]?.versions).toEqual({ 20: 7 });
		expect(result).toMatchObject({ marked: 3, of: 5 });
	});

	it('cannot be confirmed before a pick, and shows an error for a preview that failed', async () => {
		const flow = await started();
		expect(flow.canConfirm).toBe(false);
		vi.mocked(markDuplicate).mockRejectedValue(
			new ApiError(409, 'conflict', 'x', { reason: 'duplicate_chain' })
		);

		await flow.pick(3);

		expect(flow.previews?.this.status).toBe('error');
		expect(flow.canConfirm).toBe(false);
	});

	it('on a conflict says so, previews again and asks again', async () => {
		const flow = await started();
		vi.mocked(markDuplicate).mockResolvedValue(out() as never);
		await flow.pick(3);
		vi.mocked(markDuplicate).mockClear();
		vi.mocked(markDuplicate).mockRejectedValueOnce(
			new ApiError(409, 'conflict', 'x', { entry_ids: [10] })
		);
		vi.mocked(markDuplicate).mockResolvedValue(out() as never);

		const result = await flow.confirm();

		expect(result).toBeNull();
		expect(flow.failure?.kind).toBe('conflict');
		const dry = vi.mocked(markDuplicate).mock.calls.filter((c) => c[2]?.dryRun);
		expect(dry).toHaveLength(2);
		expect(flow.canConfirm).toBe(true);
	});

	it('says when the rows could not be loaded', async () => {
		vi.mocked(getStatement).mockRejectedValue(new ApiError(0, 'network_error', 'x'));
		const flow = new DuplicateFlow();
		await flow.start(row);
		expect(flow.candidatesStatus).toBe('error');
	});
});
