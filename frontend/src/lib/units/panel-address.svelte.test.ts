// The address is the one source of truth for the panel: this simulates what the layout does (an
// effect that re-syncs the panel with the address, popstate after Back and Forward) and checks
// the panel never flickers: opening stays open, closing stays closed.
import { flushSync } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getUnit } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
import { unit } from './fixtures.js';
import { UnitPanel, type PanelNav } from './panel.svelte.js';
import { registerUnitSource, type UnitSource } from './sources.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	getUnit: vi.fn(),
	listRules: vi.fn().mockResolvedValue([])
}));

/** A tab's history where Back and Forward complete LATER, as popstate does in a browser. */
function browser(start: string) {
	const stack = [start];
	let at = 0;
	let panel: UnitPanel;
	const nav: PanelNav = {
		url: () => new URL(stack[at], 'http://x.test'),
		push: (url) => {
			stack.splice(at + 1);
			stack.push(url);
			at++;
		},
		replace: (url) => (stack[at] = url),
		back: () => {
			at--;
			setTimeout(() => panel.sync(), 0); // the popstate listener of the layout
		}
	};
	return {
		nav,
		attach: (p: UnitPanel) => (panel = p),
		forward: () => {
			at++;
			setTimeout(() => panel.sync(), 0);
		},
		current: () => stack[at]
	};
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 5));
let stop: () => void;

function setup(start = '/ledger?account_id=2') {
	const tab = browser(start);
	const panel = new UnitPanel(tab.nav);
	tab.attach(panel);
	// the layout's effect: it calls sync() whenever anything it read changes
	stop = $effect.root(() => {
		$effect(() => {
			void panel.isOpen;
			void panel.unitId;
			panel.sync();
		});
	});
	flushSync();
	return { tab, panel };
}

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(getUnit).mockImplementation(async (id) => unit({ anchor_entry_id: id }));
});
afterEach(() => stop?.());

describe('the panel and the address', () => {
	it('opening stays open', async () => {
		const { tab, panel } = setup();

		panel.open(4);
		flushSync();
		await flush();

		expect(panel.isOpen).toBe(true);
		expect(panel.status).toBe('ready');
		expect(tab.current()).toBe('/ledger?account_id=2&unit=4');
		expect(getUnit).toHaveBeenCalledTimes(1);
	});

	it('closing stays closed, even while Back has not completed', async () => {
		const { tab, panel } = setup();
		panel.open(4);
		await flush();

		panel.close();
		flushSync(); // the effect runs now; the address still names the unit until popstate
		expect(panel.isOpen).toBe(false);
		await flush(); // popstate
		flushSync();

		expect(panel.isOpen).toBe(false);
		expect(tab.current()).toBe('/ledger?account_id=2');
		expect(getUnit).toHaveBeenCalledTimes(1);
	});

	it('Back after open closes it, Forward opens it again', async () => {
		const { tab, panel } = setup();
		panel.open(4);
		await flush();

		tab.nav.back();
		await flush();
		expect(panel.isOpen).toBe(false);

		tab.forward();
		await flush();
		expect(panel.isOpen).toBe(true);
		expect(panel.unitId).toBe(4);
		expect(getUnit).toHaveBeenCalledTimes(2);
	});

	it('a reload or shared link with ?unit= opens it and Close takes the parameter away', async () => {
		const { tab, panel } = setup('/review?unit=7&x=1');

		expect(panel.isOpen).toBe(true);
		await flush();
		panel.close();
		flushSync();
		await flush();

		expect(panel.isOpen).toBe(false);
		expect(tab.current()).toBe('/review?x=1');
	});

	it('stepping with [ and ] never closes it, and loads each unit once', async () => {
		const { tab, panel } = setup();
		const source: UnitSource = {
			neighbour: (id, dir) => id + dir,
			patch: () => {}
		};
		const off = registerUnitSource(source);
		panel.open(4);
		await flush();
		const seen: boolean[] = [];
		stop();
		stop = $effect.root(() => {
			$effect(() => {
				seen.push(panel.isOpen);
				panel.sync();
			});
		});
		flushSync();

		panel.step(1);
		flushSync();
		await flush();
		panel.step(1);
		flushSync();
		await flush();
		panel.step(-1);
		flushSync();
		await flush();

		expect(seen.every(Boolean)).toBe(true);
		expect(panel.unitId).toBe(5);
		expect(tab.current()).toBe('/ledger?account_id=2&unit=5');
		expect(vi.mocked(getUnit).mock.calls.map((c) => c[0])).toEqual([4, 5, 6, 5]);
		off();
	});
});

describe('the panel moves the list cursor', () => {
	it('reveals the unit shown on open and on each step, trying the entries of the unit', async () => {
		vi.mocked(getUnit).mockImplementation(async (id) =>
			unit({
				anchor_entry_id: id,
				entries: [entry({ id, unit_key: id }), entry({ id: id + 100, unit_key: id })]
			})
		);
		const revealed: number[] = [];
		const off = registerUnitSource({
			neighbour: (id, dir) => (id < 100 ? id + dir : null),
			patch: () => {},
			// the list only holds the second entry of each unit
			reveal: (id) => {
				if (id < 100) return false;
				revealed.push(id);
				return true;
			}
		});
		const { panel } = setup();

		panel.open(4);
		await flush();
		panel.step(1);
		await flush();

		expect(revealed).toEqual([104, 105]);
		off();
	});

	it('leaves a source without reveal alone', async () => {
		const off = registerUnitSource({ neighbour: () => null, patch: () => {} });
		const { panel } = setup();

		panel.open(4);
		await flush();

		expect(panel.status).toBe('ready');
		off();
	});
});
