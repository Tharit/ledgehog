import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, applyTag, createTag } from '#lib/api/index.js';
import { applyOut, tag } from '#lib/ledger/fixtures.js';
import { emptyFilter, type LedgerFilterState } from '#lib/ledger/filter.js';
import { TagAllFlow } from './tag-all.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	applyTag: vi.fn(),
	createTag: vi.fn()
}));

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const filter: LedgerFilterState = { ...emptyFilter(), account_id: [1], q: 'rewe' };

function make(current: () => LedgerFilterState = () => filter) {
	const host = { filter: current, locale: () => 'en', addTag: vi.fn(), applied: vi.fn() };
	return { flow: new TagAllFlow(host), host };
}

function body(call: number): Record<string, unknown> {
	return vi.mocked(applyTag).mock.calls[call][1] as unknown as Record<string, unknown>;
}

beforeEach(() => {
	vi.resetAllMocks();
});

describe('TagAllFlow', () => {
	it('previews with the list filter and a dry run, and never sends `all`', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut());
		const { flow } = make();

		flow.start();
		await flow.choose(tag({ id: 30 }));

		expect(applyTag).toHaveBeenCalledOnce();
		expect(vi.mocked(applyTag).mock.calls[0][0]).toBe(30);
		expect(body(0)).toMatchObject({ account_id: [1], q: 'rewe', dry_run: true, all: false });
		expect(flow.preview?.newly_tagged).toBe(3);
		expect(flow.canConfirm).toBe(true);
	});

	it('speaks about the filter of the moment it opened, even if the list changes after', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut());
		let current = filter;
		const { flow } = make(() => current);

		flow.start();
		current = { ...emptyFilter(), account_id: [9] };
		await flow.choose(tag());

		expect(body(0)).toMatchObject({ account_id: [1] });
	});

	it('confirms with the previewed count as expected_count, then patches and closes', async () => {
		vi.mocked(applyTag)
			.mockResolvedValueOnce(applyOut({ newly_tagged: 3 }))
			.mockResolvedValueOnce(
				applyOut({
					dry_run: false,
					entries: [
						{ id: 5, tag_ids: [30] },
						{ id: 6, tag_ids: [30, 31] }
					],
					settle: { error: null, touched_entry_ids: [] }
				})
			);
		const { flow, host } = make();
		flow.start();
		await flow.choose(tag({ id: 30, name: 'Lisbon trip' }));

		await flow.confirm();

		expect(body(1)).toMatchObject({ dry_run: false, expected_count: 3, all: false });
		expect(host.applied).toHaveBeenCalledWith(
			[
				{ id: 5, tag_ids: [30] },
				{ id: 6, tag_ids: [30, 31] }
			],
			'Tagged 3 entries with "Lisbon trip"'
		);
		expect(flow.open).toBe(false);
	});

	it('mentions stale derived figures when the settle failed', async () => {
		vi.mocked(applyTag)
			.mockResolvedValueOnce(applyOut({ newly_tagged: 1 }))
			.mockResolvedValueOnce(
				applyOut({ newly_tagged: 1, settle: { error: 'x', touched_entry_ids: [] } })
			);
		const { flow, host } = make();
		flow.start();
		await flow.choose(tag({ name: 'A' }));

		await flow.confirm();

		expect(host.applied.mock.calls[0][1]).toMatch(/^Tagged 1 entry with "A"\. .*stale/);
	});

	it('cannot confirm a preview that would tag nothing, and sends nothing', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut({ newly_tagged: 0 }));
		const { flow } = make();
		flow.start();
		await flow.choose(tag());

		expect(flow.canConfirm).toBe(false);
		await flow.confirm();

		expect(applyTag).toHaveBeenCalledOnce();
	});

	it('re-previews when the result changed and says what it was and is', async () => {
		vi.mocked(applyTag)
			.mockResolvedValueOnce(applyOut({ newly_tagged: 3 }))
			.mockRejectedValueOnce(
				new ApiError(409, 'conflict', 'x', {
					reason: 'filter_result_changed',
					expected: 3,
					actual: 5
				})
			)
			.mockResolvedValueOnce(applyOut({ newly_tagged: 5 }));
		const { flow, host } = make();
		flow.start();
		await flow.choose(tag());

		await flow.confirm();

		expect(flow.conflict).toBe(
			'The result changed (was 3, now 5) — please check and confirm again'
		);
		expect(flow.preview?.newly_tagged).toBe(5);
		expect(flow.open).toBe(true);
		expect(flow.canConfirm).toBe(true);
		expect(host.applied).not.toHaveBeenCalled();
		expect(body(2)).toMatchObject({ dry_run: true });
	});

	it('shows a failure by its code and keeps the dialog open', async () => {
		vi.mocked(applyTag).mockRejectedValue(new ApiError(404, 'not_found', 'x'));
		const { flow } = make();
		flow.start();
		await flow.choose(tag());

		expect(flow.error).toMatch(/no longer exists/);
		expect(flow.preview).toBeNull();
		expect(flow.canConfirm).toBe(false);
		expect(flow.open).toBe(true);
	});

	it('creates a tag in place, hands it to the host and previews it', async () => {
		vi.mocked(createTag).mockResolvedValue({
			tag: tag({ id: 41, name: 'New' }),
			settle: { error: null, touched_entry_ids: [] }
		});
		vi.mocked(applyTag).mockResolvedValue(applyOut());
		const { flow, host } = make();
		flow.start();

		await flow.create('New');
		await flush();

		expect(host.addTag).toHaveBeenCalledWith(expect.objectContaining({ id: 41 }));
		expect(flow.tag?.id).toBe(41);
		expect(vi.mocked(applyTag).mock.calls[0][0]).toBe(41);
	});

	it('drops a preview that arrives after the dialog was closed', async () => {
		let resolve!: (value: ReturnType<typeof applyOut>) => void;
		vi.mocked(applyTag).mockReturnValue(new Promise((res) => (resolve = res)));
		const { flow } = make();
		flow.start();
		const pending = flow.choose(tag());

		flow.close();
		resolve(applyOut());
		await pending;

		expect(flow.preview).toBeNull();
		expect(flow.status).toBe('idle');
	});
});
