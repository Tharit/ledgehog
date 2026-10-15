import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getEntry, listEntries } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
import { source } from '#lib/rules/fixtures.js';
import { FIND_DEBOUNCE_MS, FIND_LIMIT, RuleExampleStore } from './rule-example.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	getEntry: vi.fn(),
	listEntries: vi.fn()
}));

function page(ids: number[], total = ids.length) {
	return {
		entries: ids.map((id) => entry({ id, source: source({ counterparty_name: `Shop ${id}` }) })),
		total,
		limit: FIND_LIMIT,
		offset: 0
	};
}

beforeEach(() => {
	vi.useFakeTimers();
	vi.resetAllMocks();
});

afterEach(() => {
	vi.useRealTimers();
});

describe('RuleExampleStore: the example the page opens with', () => {
	it('shows the find box when there is none, and asks for nothing', async () => {
		const store = new RuleExampleStore();

		await store.init();

		expect(store.finding).toBe(true);
		expect(store.entry).toBeNull();
		expect(getEntry).not.toHaveBeenCalled();
	});

	it('loads it by id and shows it, not the find box', async () => {
		vi.mocked(getEntry).mockResolvedValue(entry({ id: 42 }));
		const store = new RuleExampleStore({ initialId: 42 });
		expect(store.finding).toBe(false);

		await store.init();

		expect(getEntry).toHaveBeenCalledWith(42);
		expect(store.entry?.id).toBe(42);
		expect(store.loadStatus).toBe('ready');
		expect(store.finding).toBe(false);
	});

	it('says an entry that is gone is missing and offers the find box', async () => {
		vi.mocked(getEntry).mockRejectedValue(new ApiError(404, 'not_found', 'x'));
		const onchange = vi.fn();
		const store = new RuleExampleStore({ initialId: 42, onchange });

		await store.init();

		expect(store.loadStatus).toBe('missing');
		expect(store.finding).toBe(true);
		expect(onchange).not.toHaveBeenCalled();
	});

	it('says any other failure is an error, to be tried again', async () => {
		vi.mocked(getEntry).mockRejectedValueOnce(new ApiError(0, 'network_error', 'x'));
		const store = new RuleExampleStore({ initialId: 42 });
		await store.init();
		expect(store.loadStatus).toBe('error');

		vi.mocked(getEntry).mockResolvedValueOnce(entry({ id: 42 }));
		await store.init();

		expect(store.loadStatus).toBe('ready');
	});
});

describe('RuleExampleStore: finding', () => {
	it('searches the entries list with the text, once, after the last keystroke', async () => {
		vi.mocked(listEntries).mockResolvedValue(page([1, 2]));
		const store = new RuleExampleStore();

		store.setQuery('re');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS - 50);
		store.setQuery('rewe');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS - 50);
		expect(listEntries).not.toHaveBeenCalled();
		expect(store.findStatus).toBe('loading');

		await vi.advanceTimersByTimeAsync(100);

		expect(listEntries).toHaveBeenCalledTimes(1);
		const [filter, options] = vi.mocked(listEntries).mock.calls[0];
		expect(filter.q).toBe('rewe');
		expect(filter.type).toEqual([]);
		expect(options).toMatchObject({ limit: FIND_LIMIT });
		expect(store.results.map((e) => e.id)).toEqual([1, 2]);
		expect(store.findStatus).toBe('ready');
		expect(store.highlighted).toBe(0);
	});

	it('asks for nothing for blank text and forgets the results', async () => {
		vi.mocked(listEntries).mockResolvedValue(page([1]));
		const store = new RuleExampleStore();
		store.setQuery('x');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS);

		store.setQuery('   ');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS * 2);

		expect(listEntries).toHaveBeenCalledTimes(1);
		expect(store.results).toEqual([]);
		expect(store.findStatus).toBe('idle');
	});

	it('drops an answer that a newer search has superseded', async () => {
		let release!: (value: ReturnType<typeof page>) => void;
		vi.mocked(listEntries)
			.mockReturnValueOnce(new Promise((resolve) => (release = resolve)))
			.mockResolvedValueOnce(page([9]));
		const store = new RuleExampleStore();
		store.setQuery('a');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS);

		store.setQuery('ab');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS);
		release(page([1]));
		await vi.advanceTimersByTimeAsync(0);

		expect(store.results.map((e) => e.id)).toEqual([9]);
	});

	it('says the search failed, and asks again on retry', async () => {
		vi.mocked(listEntries).mockRejectedValueOnce(new ApiError(0, 'network_error', 'x'));
		const store = new RuleExampleStore();
		store.setQuery('rewe');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS);
		expect(store.findStatus).toBe('error');

		vi.mocked(listEntries).mockResolvedValueOnce(page([5]));
		store.retry();
		await vi.advanceTimersByTimeAsync(0);

		expect(store.findStatus).toBe('ready');
		expect(store.results.map((e) => e.id)).toEqual([5]);
	});

	it('moves the highlight with the arrows and stops at both ends', async () => {
		vi.mocked(listEntries).mockResolvedValue(page([1, 2, 3]));
		const store = new RuleExampleStore();
		store.setQuery('x');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS);

		store.move(1);
		store.move(1);
		store.move(1);
		expect(store.highlighted).toBe(2);
		store.move(-1);
		store.move(-1);
		store.move(-1);
		expect(store.highlighted).toBe(0);
	});

	it('searches without a type restriction: unclassified imports (type null) are found', async () => {
		vi.mocked(listEntries).mockResolvedValue({
			entries: [entry({ id: 1, type: null, source: source({ counterparty_name: 'Shop' }) })],
			total: 1,
			limit: FIND_LIMIT,
			offset: 0
		});
		const store = new RuleExampleStore();
		store.setQuery('shop');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS);

		expect(vi.mocked(listEntries).mock.calls[0][0].type).toEqual([]);
		expect(store.results.map((e) => e.id)).toEqual([1]);
		expect(store.highlighted).toBe(0);
	});

	it('skips entries without a source: not highlighted first, not moved onto, not picked', async () => {
		vi.mocked(listEntries).mockResolvedValue({
			entries: [
				entry({ id: 1, type: 'opening', source: null }),
				entry({ id: 2, source: source({}) }),
				entry({ id: 3, type: 'valuation', source: null }),
				entry({ id: 4, source: source({}) })
			],
			total: 4,
			limit: FIND_LIMIT,
			offset: 0
		});
		const store = new RuleExampleStore();
		store.setQuery('x');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS);

		expect(store.highlighted).toBe(1);
		store.move(1);
		expect(store.highlighted).toBe(3);
		store.move(1);
		expect(store.highlighted).toBe(3);
		store.move(-1);
		expect(store.highlighted).toBe(1);
		store.move(-1);
		expect(store.highlighted).toBe(1);
		expect(store.pick(store.results[0])).toBe(false);
		expect(store.entry).toBeNull();
	});

	it('picks the highlighted result as the example and reports it', async () => {
		vi.mocked(listEntries).mockResolvedValue(page([1, 2, 3]));
		const onchange = vi.fn();
		const store = new RuleExampleStore({ onchange });
		store.setQuery('x');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS);
		store.move(1);

		expect(store.pick()).toBe(true);

		expect(store.entry?.id).toBe(2);
		expect(onchange).toHaveBeenCalledWith(2);
		expect(store.finding).toBe(false);
		expect(store.open).toBe(false);
		expect(store.query).toBe('');
		expect(store.results).toEqual([]);
	});

	it('picks nothing when there is nothing highlighted', () => {
		const onchange = vi.fn();
		const store = new RuleExampleStore({ onchange });

		expect(store.pick()).toBe(false);
		expect(onchange).not.toHaveBeenCalled();
	});

	it('does not let a search that was on its way land after a pick', async () => {
		vi.mocked(listEntries).mockResolvedValue(page([7]));
		const store = new RuleExampleStore();
		store.setQuery('x');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS);
		store.setQuery('xy');

		store.pick(entry({ id: 3, source: source() }));
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS * 2);

		expect(store.entry?.id).toBe(3);
		expect(store.results).toEqual([]);
	});
});

describe('RuleExampleStore: change, cancel and clear', () => {
	async function withExample(onchange = vi.fn()) {
		vi.mocked(getEntry).mockResolvedValue(entry({ id: 42 }));
		const store = new RuleExampleStore({ initialId: 42, onchange });
		await store.init();
		return { store, onchange };
	}

	it('opens the find box on change and keeps the example until another is chosen', async () => {
		const { store } = await withExample();

		store.change();

		expect(store.finding).toBe(true);
		expect(store.entry?.id).toBe(42);
	});

	it('goes back to the example when the find is cancelled', async () => {
		const { store, onchange } = await withExample();
		store.change();

		store.cancelFind();

		expect(store.finding).toBe(false);
		expect(store.entry?.id).toBe(42);
		expect(onchange).not.toHaveBeenCalled();
	});

	it('clears the example, reports null and shows the find box', async () => {
		const { store, onchange } = await withExample();

		store.clear();

		expect(store.entry).toBeNull();
		expect(store.finding).toBe(true);
		expect(onchange).toHaveBeenCalledWith(null);
	});

	it('closes the results first on Esc, then the find box', async () => {
		vi.mocked(listEntries).mockResolvedValue(page([1]));
		const { store } = await withExample();
		store.change();
		store.setQuery('x');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS);
		expect(store.open).toBe(true);

		store.escape();
		expect(store.open).toBe(false);
		expect(store.finding).toBe(true);

		store.escape();
		expect(store.finding).toBe(false);
		expect(store.entry?.id).toBe(42);
	});

	it('only closes the results on Esc when there is no example to go back to', async () => {
		vi.mocked(listEntries).mockResolvedValue(page([1]));
		const store = new RuleExampleStore();
		store.setQuery('x');
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS);

		store.escape();

		expect(store.open).toBe(false);
		expect(store.finding).toBe(true);
	});
});
