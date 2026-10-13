import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, applyTag, createTag, tagEntry } from '#lib/api/index.js';
import { applyOut, entry, tag } from '#lib/ledger/fixtures.js';
import { emptyFilter, type LedgerFilterState } from '#lib/ledger/filter.js';
import type { Entry } from '#lib/types/domain.js';
import { TagAllFlow } from './tag-all.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	applyTag: vi.fn(),
	createTag: vi.fn(),
	tagEntry: vi.fn()
}));

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const filter: LedgerFilterState = { ...emptyFilter(), account_id: [1], q: 'rewe' };

function make(current: () => LedgerFilterState = () => filter, marked: Entry[] = []) {
	const host = {
		filter: current,
		locale: () => 'en',
		addTag: vi.fn(),
		markedRows: () => marked,
		patch: vi.fn(),
		applied: vi.fn(),
		recover: vi.fn()
	};
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

		expect(flow.conflict).toBe('The numbers changed (was 3, now 5) — check them and try again');
		expect(flow.preview?.newly_tagged).toBe(5);
		expect(flow.open).toBe(true);
		expect(flow.canConfirm).toBe(true);
		expect(host.applied).not.toHaveBeenCalled();
		expect(body(2)).toMatchObject({ dry_run: true });
	});

	it('shows a failure by its code and keeps the dialog open', async () => {
		vi.mocked(applyTag).mockRejectedValue(new ApiError(0, 'network_error', 'x'));
		const { flow, host } = make();
		flow.start();
		await flow.choose(tag());

		expect(flow.error).toMatch(/could not be reached/);
		expect(flow.tag).not.toBeNull();
		expect(flow.preview).toBeNull();
		expect(flow.canConfirm).toBe(false);
		expect(flow.open).toBe(true);
		expect(host.recover).toHaveBeenCalledWith(
			expect.objectContaining({ code: 'network_error' }),
			'bulk'
		);
	});

	it('reopens the chooser and asks for a tag refresh when the tag is gone', async () => {
		vi.mocked(applyTag).mockRejectedValue(new ApiError(404, 'not_found', 'x'));
		const { flow, host } = make();
		flow.start();
		await flow.choose(tag());

		expect(flow.tag).toBeNull();
		expect(flow.error).toBe('This tag no longer exists — the tag list was refreshed.');
		expect(flow.open).toBe(true);
		expect(host.recover).toHaveBeenCalledWith(
			expect.objectContaining({ code: 'not_found' }),
			'bulk'
		);
	});

	it('says a duplicate name and asks for a tag refresh, without choosing a tag', async () => {
		vi.mocked(createTag).mockRejectedValue(
			new ApiError(409, 'conflict', 'x', { reason: 'duplicate_name' })
		);
		const { flow, host } = make();
		flow.start();
		await flow.create('Trip');

		expect(flow.error).toBe('A tag named "Trip" already exists — the tag list was refreshed.');
		expect(flow.tag).toBeNull();
		expect(applyTag).not.toHaveBeenCalled();
		expect(host.recover).toHaveBeenCalledWith(
			expect.objectContaining({ code: 'conflict' }),
			'bulk'
		);
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

describe('TagAllFlow: rows the user changed', () => {
	const marked = [
		entry({ id: 7 }),
		entry({ id: 8, tag_ids: [30] }),
		entry({ id: 9, type: 'opening' })
	];
	const tagged = (id: number) => ({
		changed: true,
		entry: { id, tag_ids: [30] },
		settle: { error: null, touched_entry_ids: [] }
	});

	it('counts only the marked rows the chosen tag would change', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut({ newly_tagged: 0 }));
		const { flow } = make(() => filter, marked);
		flow.start();

		await flow.choose(tag({ id: 30 }));
		expect(flow.marked).toHaveLength(3);
		expect(flow.extraRows.map((e) => e.id)).toEqual([7]);
		await flow.choose(tag({ id: 31 }));
		expect(flow.extraRows.map((e) => e.id)).toEqual([7, 8]);
	});

	it('confirms only with something to do: new entries, or opted-in rows', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut({ newly_tagged: 0 }));
		const { flow } = make(() => filter, marked);
		flow.start();
		await flow.choose(tag({ id: 30 }));

		expect(flow.includeMarked).toBe(false);
		expect(flow.canConfirm).toBe(false);
		flow.includeMarked = true;
		expect(flow.canConfirm).toBe(true);

		vi.mocked(applyTag).mockResolvedValue(applyOut({ newly_tagged: 2 }));
		await flow.choose(tag({ id: 30 }));
		flow.includeMarked = false;
		expect(flow.canConfirm).toBe(true);
	});

	it('does not confirm a checked box with no rows left to tag', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut({ newly_tagged: 0 }));
		const { flow } = make(() => filter, [entry({ id: 8, tag_ids: [30] })]);
		flow.start();
		await flow.choose(tag({ id: 30 }));
		flow.includeMarked = true;

		expect(flow.extraCount).toBe(0);
		expect(flow.canConfirm).toBe(false);
	});

	it('sends no apply request when only the rows are to be tagged', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut({ newly_tagged: 0 }));
		vi.mocked(tagEntry).mockImplementation(async (id) => tagged(id));
		const { flow, host } = make(() => filter, marked);
		flow.start();
		await flow.choose(tag({ id: 30, name: 'T' }));
		flow.includeMarked = true;

		await flow.confirm();

		expect(applyTag).toHaveBeenCalledOnce();
		expect(vi.mocked(tagEntry).mock.calls).toEqual([[7, 30]]);
		expect(host.applied).toHaveBeenCalledWith(
			[{ id: 7, tag_ids: [30] }],
			'Tagged 1 row you changed with "T"'
		);
		expect(flow.open).toBe(false);
	});

	it('applies the filter first, then the rows, and reports both', async () => {
		const order: string[] = [];
		vi.mocked(applyTag).mockImplementation(async (_id, b) => {
			if (!b.dry_run) order.push('apply');
			return b.dry_run
				? applyOut({ newly_tagged: 3 })
				: applyOut({ dry_run: false, newly_tagged: 3, entries: [{ id: 1, tag_ids: [30] }] });
		});
		vi.mocked(tagEntry).mockImplementation(async (id) => {
			order.push(`tag ${id}`);
			return tagged(id);
		});
		const { flow, host } = make(() => filter, marked);
		flow.start();
		await flow.choose(tag({ id: 30, name: 'T' }));
		flow.includeMarked = true;

		await flow.confirm();

		expect(order).toEqual(['apply', 'tag 7']);
		expect(body(1)).toMatchObject({ expected_count: 3 });
		expect(host.applied).toHaveBeenCalledWith(
			[
				{ id: 1, tag_ids: [30] },
				{ id: 7, tag_ids: [30] }
			],
			'Tagged 3 entries with "T" and 1 row you changed'
		);
	});

	it('stops at a moved result and does not touch the rows', async () => {
		vi.mocked(applyTag)
			.mockResolvedValueOnce(applyOut({ newly_tagged: 3 }))
			.mockRejectedValueOnce(
				new ApiError(409, 'conflict', 'x', {
					reason: 'filter_result_changed',
					expected: 3,
					actual: 4
				})
			)
			.mockResolvedValueOnce(applyOut({ newly_tagged: 4 }));
		const { flow, host } = make(() => filter, marked);
		flow.start();
		await flow.choose(tag({ id: 30 }));
		flow.includeMarked = true;

		await flow.confirm();

		expect(tagEntry).not.toHaveBeenCalled();
		expect(host.applied).not.toHaveBeenCalled();
		expect(flow.conflict).toMatch(/was 3, now 4/);
		expect(flow.open).toBe(true);
	});

	it('finishes the rest after a failure, then stays open with the counts', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut({ newly_tagged: 0 }));
		vi.mocked(tagEntry).mockImplementation(async (id) => {
			if (id === 7) throw new ApiError(0, 'network_error', 'x');
			return tagged(id);
		});
		const { flow, host } = make(
			() => filter,
			[entry({ id: 7 }), entry({ id: 10 }), entry({ id: 11 })]
		);
		flow.start();
		await flow.choose(tag({ id: 30 }));
		flow.includeMarked = true;

		await flow.confirm();

		expect(tagEntry).toHaveBeenCalledTimes(3);
		expect(flow.open).toBe(true);
		expect(flow.status).toBe('idle');
		expect(flow.report.join(' ')).toMatch(
			/^Tagged 2 of 3 of the rows you changed; 1 failed \(The server could not be reached/
		);
		expect(host.applied).not.toHaveBeenCalled();
		expect(host.patch).toHaveBeenCalledWith(
			expect.arrayContaining([
				{ id: 10, tag_ids: [30] },
				{ id: 11, tag_ids: [30] }
			])
		);
	});

	it('appends the stale sentence when a row write could not settle', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut({ newly_tagged: 0 }));
		vi.mocked(tagEntry).mockResolvedValue({
			changed: true,
			entry: { id: 7, tag_ids: [30] },
			settle: { error: 'x', touched_entry_ids: [] }
		});
		const { flow, host } = make(() => filter, [entry({ id: 7 })]);
		flow.start();
		await flow.choose(tag({ id: 30, name: 'T' }));
		flow.includeMarked = true;

		await flow.confirm();

		expect(host.applied.mock.calls[0][1]).toMatch(/^Tagged 1 row you changed with "T"\. .*stale/);
	});

	it('forgets the opt-in when the tag choice is reset', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut());
		const { flow } = make(() => filter, marked);
		flow.start();
		await flow.choose(tag());
		flow.includeMarked = true;

		flow.back();

		expect(flow.includeMarked).toBe(false);
	});
});
