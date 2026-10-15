import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getUnit, listRules, previewUnit } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
import { rule } from '#lib/rules/fixtures.js';
import { unitIdOf, withUnit } from './address.js';
import { UnitPanel, unitReadsRules, type PanelNav } from './panel.svelte.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import { registerUnitSource, type UnitSource } from './sources.js';
import { unit } from './fixtures.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	getUnit: vi.fn(),
	listRules: vi.fn(),
	previewUnit: vi.fn(),
	commitUnit: vi.fn()
}));

/** A history of one tab: just enough of it to see what the panel asks for. */
function fakeNav(start = '/ledger?account_id=2') {
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
	return { nav, log, current: () => stack[at] };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(previewUnit).mockImplementation(() => new Promise(() => {}));
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([rule({ id: 3, name: 'Rewe' })]);
});

describe('the address', () => {
	it('reads a positive integer only', () => {
		expect(unitIdOf(new URL('http://x/a?unit=12'))).toBe(12);
		expect(unitIdOf(new URL('http://x/a?unit=0'))).toBeNull();
		expect(unitIdOf(new URL('http://x/a?unit=abc'))).toBeNull();
		expect(unitIdOf(new URL('http://x/a'))).toBeNull();
	});

	it('sets or removes the parameter and keeps every other part', () => {
		const url = new URL('http://x/ledger?account_id=2&unit=5#top');
		expect(withUnit(url, 9)).toBe('/ledger?account_id=2&unit=9#top');
		expect(withUnit(url, null)).toBe('/ledger?account_id=2#top');
	});
});

describe('UnitPanel', () => {
	it('opens from the address (reload, shared link) and loads the unit', async () => {
		vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 7 }));
		const { nav } = fakeNav('/review?unit=7');
		const panel = new UnitPanel(nav);

		panel.sync();
		expect(panel.isOpen).toBe(true);
		expect(panel.status).toBe('loading');
		expect(panel.announcement).toBe('Loading the unit…');
		await flush();

		expect(panel.status).toBe('ready');
		expect(panel.unit?.anchor_entry_id).toBe(7);
		expect(getUnit).toHaveBeenCalledWith(7, expect.any(AbortSignal));
	});

	it('open pushes a history entry; Close goes back', async () => {
		vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 4 }));
		const { nav, log } = fakeNav();
		const panel = new UnitPanel(nav);

		panel.open(4);
		await flush();
		expect(log).toEqual(['push /ledger?account_id=2&unit=4']);

		panel.close();
		expect(log.at(-1)).toBe('back');
		expect(panel.isOpen).toBe(false);
		expect(panel.status).toBe('idle');
	});

	it('Close removes the parameter, keeping the rest, when it was opened from the address', async () => {
		vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 4 }));
		const { nav, log } = fakeNav('/ledger?account_id=2&unit=4');
		const panel = new UnitPanel(nav);
		panel.sync();
		await flush();

		panel.close();

		expect(log).toEqual(['replace /ledger?account_id=2']);
	});

	it('names the anchor in the address when opened by another entry of the unit', async () => {
		vi.mocked(getUnit).mockResolvedValue(
			unit({ anchor_entry_id: 3, entries: [entry({ id: 3 }), entry({ id: 8 })] })
		);
		const { nav, log, current } = fakeNav();
		const panel = new UnitPanel(nav);

		panel.open(8);
		await flush();

		expect(panel.unitId).toBe(3);
		expect(log.at(-1)).toBe('replace /ledger?account_id=2&unit=3');
		expect(current()).toContain('unit=3');
	});

	describe('stepping', () => {
		function source(map: Record<string, number | null>): UnitSource {
			return {
				neighbour: (id, dir) => map[`${id}:${dir}`] ?? null,
				patch: () => {},
				position: (id) => (id === 4 ? { index: 12, total: 214 } : null)
			};
		}

		it('replaces the history entry and loads the neighbour', async () => {
			vi.mocked(getUnit).mockImplementation(async (id) => unit({ anchor_entry_id: id }));
			const off = registerUnitSource(source({ '4:1': 9 }));
			const { nav, log } = fakeNav();
			const panel = new UnitPanel(nav);
			panel.open(4);
			await flush();
			expect(panel.position).toEqual({ index: 12, total: 214 });

			panel.step(1);
			await flush();

			expect(log.at(-1)).toBe('replace /ledger?account_id=2&unit=9');
			expect(panel.unit?.anchor_entry_id).toBe(9);
			off();
		});

		it('says so at the end of the list and stays', async () => {
			vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 4 }));
			const off = registerUnitSource(source({}));
			const { nav, log } = fakeNav();
			const panel = new UnitPanel(nav);
			panel.open(4);
			await flush();

			panel.step(1);

			expect(panel.stepNotice).toBe('This is the last unit.');
			expect(panel.announcement).toBe('This is the last unit.');
			expect(log).toHaveLength(1);
			off();
		});

		it('asks the source with every entry of the unit when the anchor is not in the list', async () => {
			vi.mocked(getUnit).mockResolvedValue(
				unit({ anchor_entry_id: 3, entries: [entry({ id: 3 }), entry({ id: 8 })] })
			);
			const off = registerUnitSource(source({ '8:-1': 2 }));
			const { nav } = fakeNav();
			const panel = new UnitPanel(nav);
			panel.open(3);
			await flush();

			vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 2 }));
			panel.step(-1);
			await flush();

			expect(panel.unitId).toBe(2);
			off();
		});

		it('explains that stepping needs a list when there is none', async () => {
			vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 4 }));
			const { nav } = fakeNav('/ledger?unit=4');
			const panel = new UnitPanel(nav);
			panel.sync();
			await flush();

			panel.step(1);

			expect(panel.stepNotice).toMatch(/Open a unit from/);
		});
	});

	it('keeps the error to retry', async () => {
		vi.mocked(getUnit)
			.mockRejectedValueOnce(new ApiError(0, 'network_error', 'down'))
			.mockResolvedValueOnce(unit({ anchor_entry_id: 4 }));
		const { nav } = fakeNav();
		const panel = new UnitPanel(nav);

		panel.open(4);
		await flush();
		expect(panel.status).toBe('error');
		expect(panel.error?.code).toBe('network_error');

		panel.retry();
		await flush();
		expect(panel.status).toBe('ready');
	});

	it('answers a 404 as "no review", not as an error', async () => {
		vi.mocked(getUnit).mockRejectedValue(new ApiError(404, 'not_found', 'x'));
		const { nav } = fakeNav();
		const panel = new UnitPanel(nav);

		panel.open(4);
		await flush();

		expect(panel.status).toBe('missing');
		expect(panel.announcement).toBe('This entry has no review.');
	});

	it('ignores an answer that arrives after stepping on', async () => {
		let resolveFirst!: (u: ReturnType<typeof unit>) => void;
		vi.mocked(getUnit)
			.mockReturnValueOnce(new Promise((resolve) => (resolveFirst = resolve)))
			.mockResolvedValueOnce(unit({ anchor_entry_id: 9 }));
		const { nav } = fakeNav();
		const panel = new UnitPanel(nav);
		panel.open(4);
		panel.open(9);
		await flush();

		resolveFirst(unit({ anchor_entry_id: 4 }));
		await flush();

		expect(panel.unit?.anchor_entry_id).toBe(9);
	});

	it('follows Back (the address lost the parameter) and loads rule names only when needed', async () => {
		vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 4 }));
		const plain = fakeNav('/ledger?unit=4');
		const panel = new UnitPanel(plain.nav);
		panel.sync();
		await flush();
		expect(listRules).toHaveBeenCalledTimes(1); // the fixture's payee key is a rule's
		expect(panel.rules.loaded).toBe(true);
		expect(panel.rules.name(3)).toBe('Rewe');

		plain.nav.replace('/ledger');
		panel.sync();
		expect(panel.isOpen).toBe(false);
	});

	it('asks for the rules again on every unit load, so a rule made since is not "deleted"', async () => {
		vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 4 }));
		const { nav } = fakeNav();
		const panel = new UnitPanel(nav);
		panel.open(4);
		await flush();
		expect(listRules).toHaveBeenCalledTimes(1);

		vi.mocked(listRules).mockResolvedValue([
			rule({ id: 3, name: 'Rewe' }),
			rule({ id: 8, name: 'Lidl' })
		]);
		panel.open(5);
		await flush();

		expect(listRules).toHaveBeenCalledTimes(2);
		expect(panel.rules.name(8)).toBe('Lidl');
		expect(panel.rules.loaded).toBe(true);
	});

	it('does not load rules for a unit with none', () => {
		expect(
			unitReadsRules(
				unit({ entries: [entry({ id: 1, derivation: { category: { pass: 'history' } } })] })
			)
		).toBe(false);
		expect(unitReadsRules(unit())).toBe(true);
	});
});
