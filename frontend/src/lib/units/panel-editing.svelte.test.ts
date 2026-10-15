// The panel's editing flow: asking before a draft is lost, and advancing after a commit (patterns §5).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { commitUnit, getUnit, listRules, previewUnit } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import { committed, preview, unit } from './fixtures.js';
import { UnitPanel, type PanelNav } from './panel.svelte.js';
import { registerUnitSource, type UnitSource } from './sources.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	getUnit: vi.fn(),
	listRules: vi.fn(),
	previewUnit: vi.fn(),
	commitUnit: vi.fn()
}));

function fakeNav(start = '/review') {
	const stack = [start];
	let at = 0;
	const log: string[] = [];
	const nav: PanelNav = {
		url: () => new URL(stack[at], 'http://x.test'),
		push: (url) => {
			stack.splice(at + 1);
			stack.push(url);
			at++;
			log.push(`push ${url}`);
		},
		replace: (url) => {
			stack[at] = url;
			log.push(`replace ${url}`);
		},
		back: () => {
			at--;
			log.push('back');
		}
	};
	return { nav, log };
}

const flush = async () => {
	for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0));
};

const oneEntry = (id: number) =>
	unit({ anchor_entry_id: id, entries: [entry({ id, unit_key: id, version: id })] });

let off: (() => void) | null = null;

function source(over: Partial<UnitSource> & { next?: Record<number, number | null> } = {}) {
	const { next = {}, ...rest } = over;
	const full: UnitSource = {
		neighbour: vi.fn((id: number, dir: -1 | 1) => (dir === 1 ? (next[id] ?? null) : null)),
		patch: vi.fn(),
		reveal: vi.fn(() => true),
		notice: vi.fn(),
		...rest
	};
	off = registerUnitSource(full);
	return full;
}

async function openPanel(id = 1) {
	const { nav, log } = fakeNav();
	const panel = new UnitPanel(nav);
	panel.open(id);
	await flush();
	return { panel, log };
}

beforeEach(() => {
	vi.resetAllMocks();
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([]);
	vi.mocked(getUnit).mockImplementation(async (id) => oneEntry(id));
	vi.mocked(previewUnit).mockImplementation(async (draft) =>
		preview(oneEntry(draft.anchor_entry_id))
	);
	vi.mocked(commitUnit).mockImplementation(async (draft) =>
		committed(oneEntry(draft.anchor_entry_id))
	);
});
afterEach(() => off?.());

describe('a draft with changes asks before it is lost', () => {
	it('closing asks, Cancel keeps the draft and returns focus to the panel', async () => {
		source();
		const { panel } = await openPanel();
		panel.flow.setField(1, 'category', 11);
		const token = panel.focusToken;

		panel.close();
		expect(panel.leave).not.toBeNull();
		expect(panel.isOpen).toBe(true);

		panel.cancelLeave();
		expect(panel.leave).toBeNull();
		expect(panel.isOpen).toBe(true);
		expect(panel.flow.isDirty).toBe(true);
		expect(panel.focusToken).toBe(token + 1);
	});

	it('Discard closes, and the draft is gone', async () => {
		source();
		const { panel } = await openPanel();
		panel.flow.setField(1, 'category', 11);

		panel.close();
		panel.confirmLeave();

		expect(panel.isOpen).toBe(false);
		expect(panel.flow.draft).toBeNull();
	});

	it('closing a clean panel does not ask', async () => {
		source();
		const { panel } = await openPanel();
		panel.close();
		expect(panel.leave).toBeNull();
		expect(panel.isOpen).toBe(false);
	});

	it('stepping asks, and Discard steps', async () => {
		source({ next: { 1: 2 } });
		const { panel } = await openPanel();
		panel.flow.reresolve();

		panel.step(1);
		expect(panel.unitId).toBe(1);
		expect(panel.leave).not.toBeNull();

		panel.confirmLeave();
		await flush();
		expect(panel.unitId).toBe(2);
		expect(panel.flow.isDirty).toBe(false);
	});

	it('opening a consequence row asks first, and opens it when the draft is clean', async () => {
		source();
		const { panel } = await openPanel();
		panel.openEntry(5);
		await flush();
		expect(panel.unitId).toBe(5);

		panel.flow.reresolve();
		panel.openEntry(6);
		expect(panel.unitId).toBe(5);
		expect(panel.leave).not.toBeNull();
		panel.confirmLeave();
		await flush();
		expect(panel.unitId).toBe(6);
	});

	it('does not close, step or ask while a commit is under way', async () => {
		source({ next: { 1: 2 } });
		const { panel } = await openPanel();
		let release!: () => void;
		vi.mocked(commitUnit).mockImplementation(
			() => new Promise((resolve) => (release = () => resolve(committed(oneEntry(1)))))
		);
		const pending = panel.flow.commit();
		expect(panel.flow.committing).toBe(true);

		panel.close();
		panel.step(1);

		expect(panel.isOpen).toBe(true);
		expect(panel.unitId).toBe(1);
		expect(panel.leave).toBeNull();
		release();
		await pending;
	});
});

describe('after a commit the panel moves on', () => {
	it('patches the list, stays open and shows the next unit', async () => {
		const list = source({ next: { 1: 2 } });
		const { panel, log } = await openPanel();
		const token = panel.focusToken;

		await panel.flow.commit();
		await flush();

		expect(list.patch).toHaveBeenCalledWith(
			expect.objectContaining({ resolved: [1], anchor_entry_id: 1 })
		);
		expect(panel.isOpen).toBe(true);
		expect(panel.unitId).toBe(2);
		expect(panel.unit?.anchor_entry_id).toBe(2);
		expect(log.at(-1)).toBe('replace /review?unit=2');
		expect(panel.focusToken).toBeGreaterThan(token);
		expect(panel.flow.previewStatus).toBe('ready'); // the next preview follows the commit
	});

	it('skips units this session already committed', async () => {
		vi.mocked(commitUnit).mockImplementation(async (draft) => {
			const both = unit({
				anchor_entry_id: draft.anchor_entry_id,
				entries: [entry({ id: 1, unit_key: 1 }), entry({ id: 2, unit_key: 1 })]
			});
			return committed(both);
		});
		source({ next: { 1: 2, 2: 3 } });
		const { panel } = await openPanel();

		await panel.flow.commit();
		await flush();

		expect(panel.unitId).toBe(3);
	});

	it('ends with a notice and the cursor on the last unit when there is none left', async () => {
		const list = source({ next: {}, finishedText: 'Review done' });
		const { panel, log } = await openPanel();

		await panel.flow.commit();
		await flush();

		expect(panel.isOpen).toBe(false);
		expect(list.notice).toHaveBeenCalledWith('Review done');
		// the cursor lands on the unit just committed without visiting it: its marks stay
		expect(list.reveal).toHaveBeenCalledWith(1, false);
		expect(list.reveal).toHaveBeenCalledWith(1, true); // on open, it visited
		expect(log).toContain('back');
	});

	it('says "No more units" for a list that does not name its end', async () => {
		const list = source({ next: {} });
		const { panel } = await openPanel();
		await panel.flow.commit();
		await flush();
		expect(list.notice).toHaveBeenCalledWith('No more units');
	});

	it('loads more of the list when the loaded rows end, and carries on', async () => {
		const next: Record<number, number | null> = {};
		const loadMore = vi.fn(async () => {
			next[1] = 7;
			return true;
		});
		source({ next, loadMore });
		const { panel } = await openPanel();

		await panel.flow.commit();
		await flush();

		expect(loadMore).toHaveBeenCalled();
		expect(panel.unitId).toBe(7);
	});

	it('closes when loading more adds nothing', async () => {
		const list = source({ loadMore: async () => false });
		const { panel } = await openPanel();
		await panel.flow.commit();
		await flush();
		expect(panel.isOpen).toBe(false);
		expect(list.notice).toHaveBeenCalled();
	});

	it('closes quietly when it was opened from nowhere (no list to advance through)', async () => {
		const { panel } = await openPanel();
		await panel.flow.commit();
		await flush();
		expect(panel.isOpen).toBe(false);
	});

	it('keeps the draft and the panel when the commit fails', async () => {
		source({ next: { 1: 2 } });
		const { panel } = await openPanel();
		panel.flow.setField(1, 'category', 11);
		await flush();
		vi.mocked(commitUnit).mockRejectedValueOnce(
			new (await import('#lib/api/index.js')).ApiError(409, 'try_again', 'x')
		);

		await panel.flow.commit();
		await flush();

		expect(panel.unitId).toBe(1);
		expect(panel.flow.isDirty).toBe(true);
		expect(panel.flow.notice?.action?.label).toBe('Try again');
	});
});
