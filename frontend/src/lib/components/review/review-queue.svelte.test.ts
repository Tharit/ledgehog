import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { account, category, entry, payee } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { changes } from '#lib/stores/changes.svelte.js';
import { ReviewQueueStore } from '#lib/stores/review-queue.svelte.js';
import { apiError, committed, preview, queue, section, unit } from '#lib/units/fixtures.js';
import { unitPanel } from '#lib/units/panel-instance.js';
import { activeUnitSource } from '#lib/units/sources.js';
import { accounts as accountDialog } from '#lib/accounts/controller.svelte.js';
import ReviewQueue from './review-queue.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	getQueue: vi.fn(),
	listRules: vi.fn(),
	getUnit: vi.fn(),
	previewUnit: vi.fn(),
	commitUnit: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));
const { getQueue } = api;
vi.mock('#lib/units/panel-instance.js', () => ({ unitPanel: { open: vi.fn() } }));

const lookups = buildLookups({
	accounts: [account({ id: 1, name: 'Giro' }), account({ id: 2, name: 'Savings' })],
	categories: [category({ id: 10, name: 'Groceries' })],
	payees: [payee({ id: 20, name: 'REWE' })]
});

const history = { pass: 'history', basis: { agree: 3, of: 4, since: '2026-03-14' } };
function flow(id: number, text: string, over = {}) {
	return unit({
		anchor_entry_id: id,
		entries: [
			entry({
				id,
				unit_key: id,
				description: text,
				display_description: { text, from: 'description' },
				category_id: 10,
				derivation: { category: history },
				review_flags: ['unconfirmed'],
				...over
			})
		]
	});
}

async function shown(
	sections: Parameters<typeof queue>[0],
	extra: Partial<ReturnType<typeof queue>> = {}
) {
	vi.mocked(getQueue).mockResolvedValue({ ...queue(sections), ...extra });
	const store = new ReviewQueueStore();
	await store.load();
	render(ReviewQueue, { props: { store, lookups, locale: 'en' } });
	return store;
}

const key = (name: string) => fireEvent.keyDown(document.body, { key: name });

beforeEach(() => {
	vi.resetAllMocks();
	changes.modelPending = 0;
});

describe('ReviewQueue: what the model has not yet answered', () => {
	it('marks each entry the model is still looking at, and no other', async () => {
		await shown({
			pending_review: [
				flow(1, 'REWE', { model_pending: true }),
				unit({
					anchor_entry_id: 2,
					entries: [
						entry({ id: 2, unit_key: 2 }),
						entry({ id: 3, unit_key: 2, model_pending: true })
					]
				}),
				flow(4, 'Edeka')
			]
		});

		const marks = screen.getAllByRole('img', { name: 'The model is still looking at this' });
		expect(marks).toHaveLength(2);
		expect(marks[0]).toHaveAttribute('title', 'The model is still looking at this');
		expect(marks[0].closest('[data-unit]')).toHaveAttribute('data-unit', '1');
		// the second entry of a unit, not its first
		expect(marks[1].closest('[data-unit]')).toHaveAttribute('data-unit', '2');
		expect(marks[1].closest('[role="row"]')).toHaveAttribute('data-entry-id', '3');
	});

	it('says how many entries the model is looking at, from the change poll, only while there are some', async () => {
		await shown({ pending_review: [flow(1, 'REWE')] });
		expect(screen.queryByText(/The model is looking at/)).toBeNull();

		changes.modelPending = 2;
		expect(await screen.findByText('The model is looking at 2 entries.')).toBeInTheDocument();
		changes.modelPending = 1;
		expect(await screen.findByText('The model is looking at 1 entry.')).toBeInTheDocument();
		changes.modelPending = 0;
		await waitFor(() => expect(screen.queryByText(/The model is looking at/)).toBeNull());
	});

	it('stays a snapshot: the poll count does not reload the queue', async () => {
		await shown({ pending_review: [flow(1, 'REWE', { model_pending: true })] });
		changes.modelPending = 3;
		await screen.findByText('The model is looking at 3 entries.');
		expect(getQueue).toHaveBeenCalledTimes(1);
	});
});

describe('ReviewQueue', () => {
	it('has three headed sections with their counts, and empty ones say what belongs there', async () => {
		await shown({ pending_review: [flow(1, 'REWE'), flow(2, 'Edeka')] });

		const pending = screen.getByRole('heading', { name: /Pending review/ });
		expect(pending).toHaveTextContent('(2)');
		expect(screen.getByRole('heading', { name: /Needs an account/ })).toHaveTextContent('(0)');
		expect(screen.getByRole('heading', { name: /Waiting/ })).toHaveTextContent('(0)');
		expect(screen.getByText('No transfer is missing an account.')).toBeInTheDocument();
		expect(screen.getByText(/Nothing is waiting/)).toBeInTheDocument();
	});

	it('is one flush card per section, the title row over the header row in one tinted band', async () => {
		await shown({ pending_review: [flow(1, 'REWE')] });

		const section = document.querySelector('[data-section="pending_review"]')!;
		const title = section.querySelector('[data-slot="card-title"]')!;
		expect(title).toHaveClass('bg-muted');
		expect(title.nextElementSibling).toHaveAttribute('role', 'grid');
		expect(title.querySelector('h2')).toHaveTextContent('Pending review (1)');
		const header = section.querySelector('[role="row"]')!;
		expect(header).toHaveClass('bg-muted');
		expect(header).not.toHaveClass('rounded-t-[11px]');
		const empty = document.querySelector('[data-section="waiting"]')!;
		expect(empty.querySelector('[data-slot="card-title"]')).not.toBeNull();
		expect(empty.querySelector('[data-slot="section-empty"]')).not.toBeNull();
	});

	it('gives each section heading its review state glyph, bare, and no tile', async () => {
		await shown({ pending_review: [flow(1, 'REWE')] });

		const glyphs = {
			'Pending review': 'circle-dashed',
			'Needs an account': 'unlink',
			Waiting: 'clock'
		};
		for (const [title, glyph] of Object.entries(glyphs)) {
			const heading = screen.getByRole('heading', { name: new RegExp(title) });
			const svg = heading.querySelector('svg');
			expect(svg).toHaveClass(`lucide-${glyph}`);
			expect(svg).toHaveClass('text-muted-foreground');
			expect(svg).toHaveAttribute('width', '16');
			expect(heading.querySelector('span[style*="--tile-fg"]')).toBeNull();
		}
	});

	it('lists units by date as given, in the entry-row shape, with no basis column', async () => {
		await shown({
			pending_review: [
				flow(1, 'REWE'),
				flow(2, 'Rent', {
					derivation: { category: { pass: 'rule', basis: { rule_id: 3 } } }
				})
			]
		});

		const grid = screen.getByRole('grid', { name: 'Pending review' });
		expect(within(grid).queryByRole('columnheader', { name: 'Basis' })).toBeNull();
		expect(within(grid).queryByText(/history 3 of 4|rule: Rewe/)).toBeNull();
		expect(within(grid).getAllByRole('row').length).toBeGreaterThanOrEqual(3);
	});

	it('joins the entries of a split and shows both legs of a pair, one block per unit', async () => {
		await shown({
			pending_review: [
				unit({
					anchor_entry_id: 1,
					entries: [
						entry({
							id: 1,
							unit_key: 1,
							description: 'Amazon',
							display_description: { text: 'Amazon', from: 'description' }
						}),
						entry({
							id: 2,
							unit_key: 1,
							description: 'Amazon',
							display_description: { text: 'Amazon', from: 'description' }
						})
					]
				}),
				unit({
					anchor_entry_id: 3,
					entries: [
						entry({
							id: 3,
							unit_key: 3,
							type: 'transfer',
							account_id: 1,
							description: 'Out',
							display_description: { text: 'Out', from: 'description' },
							counterpart_entry_id: 4
						}),
						entry({
							id: 4,
							unit_key: 3,
							type: 'transfer',
							account_id: 2,
							description: 'In',
							display_description: { text: 'In', from: 'description' },
							counterpart_entry_id: 3
						})
					]
				})
			]
		});

		const groups = document.querySelectorAll('[role="rowgroup"]');
		expect(groups).toHaveLength(2);
		expect(within(groups[0] as HTMLElement).getAllByRole('row')).toHaveLength(2);
		expect(within(groups[1] as HTMLElement).getAllByRole('row')).toHaveLength(2);
	});

	it('draws each multi-entry unit as a group with a faint left bar and a joint highlight, the split with its total marker', async () => {
		await shown({
			pending_review: [
				unit({
					anchor_entry_id: 1,
					entries: [
						entry({ id: 1, unit_key: 1, amount: { amount: -300, currency: 'EUR' } }),
						entry({ id: 2, unit_key: 1, amount: { amount: -200, currency: 'EUR' } })
					]
				}),
				unit({
					anchor_entry_id: 3,
					entries: [
						entry({ id: 3, unit_key: 3, type: 'transfer', counterpart_entry_id: 4 }),
						entry({ id: 4, unit_key: 3, type: 'transfer', counterpart_entry_id: 3 })
					]
				}),
				flow(5, 'Single')
			]
		});

		const groups = document.querySelectorAll<HTMLElement>('[role="rowgroup"]');
		expect(groups).toHaveLength(3);
		for (const group of [groups[0], groups[1]]) {
			expect(group.className).toContain('border-l-2');
			expect(group.className).toContain('group/unit');
			for (const row of group.querySelectorAll('[role="row"]'))
				expect(row.className).toContain('group-hover/unit:bg-row-hover');
		}
		expect(groups[2].className).not.toContain('group/unit');
		const markers = document.querySelectorAll('[data-unit-marker]');
		expect(markers).toHaveLength(2);
		expect(groups[0].querySelector('[data-entry-id="1"]')!.contains(markers[0])).toBe(true);
		expect(groups[0].querySelector('[data-entry-id="2"]')!.contains(markers[1])).toBe(true);
		for (const marker of markers)
			expect(marker.getAttribute('title')).toMatch(/^Split total .*5\.00/);
	});

	it('the cursor highlights every row of its unit', async () => {
		await shown({
			pending_review: [
				unit({
					anchor_entry_id: 1,
					entries: [entry({ id: 1, unit_key: 1 }), entry({ id: 2, unit_key: 1 })]
				})
			]
		});
		await key('j');

		expect(document.querySelectorAll('[role="row"][data-cursor]')).toHaveLength(2);
	});

	it('is empty only when the whole queue is: "Nothing to review", with a link to the ledger', async () => {
		await shown({});

		expect(screen.getByText('Nothing to review')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Open the ledger' })).toHaveAttribute(
			'href',
			'/ledger'
		);
		expect(screen.queryByRole('heading', { name: /Pending review/ })).toBeNull();
	});

	it('shows a failure with Try again', async () => {
		vi.mocked(getQueue).mockRejectedValue(apiError(0, 'network_error'));
		const store = new ReviewQueueStore();
		await store.load();
		render(ReviewQueue, { props: { store, lookups } });

		expect(screen.getByRole('alert')).toHaveTextContent('review queue could not be loaded');
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [flow(1, 'REWE')] }));
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		await waitFor(() => expect(store.status).toBe('ready'));
	});

	it('offers "Load more" per section while a cursor is left, and asks for that section', async () => {
		vi.mocked(getQueue).mockResolvedValueOnce({
			...queue(),
			sections: [
				section('pending_review', [flow(1, 'REWE')], { total: 3, next_cursor: 'c1' }),
				section('needs_account', []),
				section('waiting', [])
			],
			total: 3
		});
		const store = new ReviewQueueStore();
		await store.load();
		render(ReviewQueue, { props: { store, lookups } });
		expect(screen.getByText('1 of 3')).toBeInTheDocument();
		vi.mocked(getQueue).mockResolvedValueOnce({
			...queue(),
			sections: [section('pending_review', [flow(2, 'Edeka'), flow(3, 'Lidl')], { total: 3 })]
		});

		await fireEvent.click(screen.getByRole('button', { name: 'Load more' }));

		await waitFor(() => expect(screen.getByText('Lidl')).toBeInTheDocument());
		expect(getQueue).toHaveBeenLastCalledWith({
			section: 'pending_review',
			cursor: 'c1',
			accountIds: [],
			cut: 'date'
		});
		expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
	});
});

describe('ReviewQueue: the pending section is cut by month and day', () => {
	const on = (id: number, booked_on: string, text = `Unit ${id}`) => flow(id, text, { booked_on });
	const dated = () => ({
		pending_review: [
			on(1, '2026-11-20'),
			on(2, '2026-11-20'),
			on(3, '2026-11-02'),
			on(4, '2026-10-30'),
			// a split drawn under the day of its first entry, whole
			unit({
				anchor_entry_id: 5,
				entries: [
					entry({ id: 5, unit_key: 5, booked_on: '2026-10-30', review_flags: ['unconfirmed'] }),
					entry({ id: 6, unit_key: 5, booked_on: '2026-10-29', review_flags: ['unconfirmed'] })
				]
			})
		],
		needs_account: [
			unit({ ...flow(7, 'Out 7', { booked_on: '2026-11-15' }), needs_account: { currency: 'USD' } })
		]
	});

	it('has month and day rows and no date column, no sums', async () => {
		await shown(dated());

		const grid = screen.getByRole('grid', { name: 'Pending review' });
		expect(within(grid).queryByRole('columnheader', { name: 'Date' })).toBeNull();
		const months = [...grid.querySelectorAll('[data-slot="month-row"]')].map(
			(r) => r.querySelector('[data-slot="subgroup-label"]')!.textContent
		);
		expect(months).toEqual(['November 2026', 'October 2026']);
		const days = [...grid.querySelectorAll('[data-slot="band-label"]')].map((d) => d.textContent);
		expect(days).toHaveLength(3);
		const november = grid.querySelector('[data-month="2026-11"]')!;
		expect(november.querySelectorAll('[data-day]')).toHaveLength(2);
		expect(
			november.querySelector('[data-day="2026-11/2026-11-20"]')!.querySelectorAll('[data-unit]')
		).toHaveLength(2);
		// the split sits whole under the day of its first entry
		const october = grid.querySelector('[data-day="2026-10/2026-10-30"]')!;
		expect(october.querySelectorAll('[data-unit="5"] [data-entry-id]')).toHaveLength(2);
		expect(grid.querySelectorAll('[data-col="date"]')).toHaveLength(0);
	});

	it('the other sections keep the date column, without day rows', async () => {
		await shown(dated());

		const grid = screen.getByRole('grid', { name: 'Needs an account' });
		expect(within(grid).getByRole('columnheader', { name: 'Date' })).toBeInTheDocument();
		expect(grid.querySelectorAll('[data-col="date"]').length).toBeGreaterThan(0);
		expect(grid.querySelector('[data-slot="band-label"]')).toBeNull();
	});

	it('the cursor and Enter run over the units across the bands, in the order drawn', async () => {
		const store = await shown(dated());

		const drawn = [...document.querySelectorAll('[data-section="pending_review"] [data-unit]')].map(
			(n) => Number(n.getAttribute('data-unit'))
		);
		expect(drawn).toEqual([1, 2, 3, 4, 5]);
		for (let i = 0; i < 3; i++) await key('j');
		const cursor = () =>
			document
				.querySelector('[data-section="pending_review"] [aria-selected="true"]')!
				.closest('[data-unit]')!
				.getAttribute('data-unit');
		expect(cursor()).toBe('3'); // across the day band into the next
		await key('j');
		await key('j');
		expect(cursor()).toBe('5'); // across the month band
		await key('Enter');
		expect(vi.mocked(unitPanel.open)).toHaveBeenCalledWith(5, expect.anything());
		expect(store.units.map((u) => u.anchor_entry_id)).toEqual([1, 2, 3, 4, 5, 7]);
	});
});

describe('ReviewQueue: marks after a commit', () => {
	const again = (id: number, text: string, flags: string[] = ['unconfirmed']) =>
		entry({
			id,
			unit_key: id,
			description: text,
			display_description: { text, from: 'description' },
			category_id: 10,
			derivation: { category: history },
			review_flags: flags as never
		});
	const rowOf = (text: string) =>
		screen.getAllByRole('row').find((r) => r.textContent?.includes(text))!;

	async function committedRows() {
		const store = await shown({
			pending_review: [flow(1, 'REWE'), flow(2, 'Edeka'), flow(3, 'Lidl')]
		});
		store.source.patch({
			entries: [again(1, 'REWE', []), again(2, 'Edeka'), again(3, 'Lidl', [])],
			resolved: [1, 2],
			confirmed: [1]
		});
		return store;
	}

	it('mutes every committed row; only the confirmed one has the check, the other keeps its badge', async () => {
		await committedRows();

		await waitFor(() => expect(rowOf('REWE')).toHaveAttribute('data-resolved'));
		expect(within(rowOf('REWE')).getByRole('img', { name: 'Confirmed' })).toBeInTheDocument();
		expect(rowOf('Edeka')).toHaveAttribute('data-resolved');
		expect(within(rowOf('Edeka')).queryByRole('img', { name: 'Confirmed' })).toBeNull();
		expect(rowOf('Edeka').querySelector('[data-flag="unconfirmed"]')).not.toBeNull();
		// a row of a unit that was not committed, changed as a consequence: the ochre bar only
		expect(rowOf('Lidl')).not.toHaveAttribute('data-resolved');
		expect(rowOf('Lidl')).toHaveAttribute('data-changed');
	});

	it('keeps the muting and the check when the cursor visits; only the ochre bar fades', async () => {
		await committedRows();
		await waitFor(() => expect(rowOf('Lidl')).toHaveAttribute('data-changed'));

		await key('j');
		await key('j');
		await key('j');

		await waitFor(() => expect(rowOf('Lidl')).not.toHaveAttribute('data-changed'));
		expect(rowOf('REWE')).toHaveAttribute('data-resolved');
		expect(within(rowOf('REWE')).getByRole('img', { name: 'Confirmed' })).toBeInTheDocument();
		expect(rowOf('Edeka')).toHaveAttribute('data-resolved');
	});
});

describe('ReviewQueue: the keyboard', () => {
	it('has the shared keyboard help: a button, and ? and Esc', async () => {
		await shown({ pending_review: [flow(1, 'REWE')] });

		await fireEvent.click(screen.getByRole('button', { name: /Keyboard shortcuts/ }));
		const help = screen.getByRole('region', { name: 'Keyboard shortcuts' });
		expect(help).toHaveTextContent('Open the unit for review');
		expect(help).not.toHaveTextContent('previous or next unit');
		await key('Escape');
		expect(screen.queryByRole('region', { name: 'Keyboard shortcuts' })).toBeNull();
		await key('?');
		expect(screen.getByRole('region', { name: 'Keyboard shortcuts' })).toBeInTheDocument();
	});

	it('moves a cursor over units, not entries, and stops at the ends', async () => {
		await shown({
			pending_review: [
				unit({
					anchor_entry_id: 1,
					entries: [
						entry({
							id: 1,
							unit_key: 1,
							description: 'Amazon',
							display_description: { text: 'Amazon', from: 'description' }
						}),
						entry({
							id: 2,
							unit_key: 1,
							description: 'Amazon',
							display_description: { text: 'Amazon', from: 'description' }
						})
					]
				}),
				flow(3, 'REWE')
			]
		});

		await key('j');
		const selected = () =>
			screen.getAllByRole('row').filter((r) => r.getAttribute('aria-selected') === 'true');
		expect(selected()).toHaveLength(2); // both entries of the first unit
		await key('ArrowDown');
		expect(selected()).toHaveLength(1);
		expect(selected()[0]).toHaveTextContent('REWE');
		await key('j');
		expect(selected()[0]).toHaveTextContent('REWE');
		await key('k');
		expect(selected()).toHaveLength(2);
	});

	it('Enter opens the panel on the unit anchor, with the queue as the source', async () => {
		const store = await shown({ pending_review: [flow(7, 'REWE'), flow(9, 'Edeka')] });
		await key('j');
		await key('j');

		await key('Enter');

		expect(vi.mocked(unitPanel.open).mock.calls[0][0]).toBe(9);
		expect(activeUnitSource()).toBe(store.source);
	});

	it('puts the cursor on the unit the panel shows, both entries of a split', async () => {
		const store = await shown({
			pending_review: [
				flow(1, 'REWE'),
				unit({
					anchor_entry_id: 3,
					entries: [
						entry({
							id: 3,
							unit_key: 3,
							description: 'Amazon',
							display_description: { text: 'Amazon', from: 'description' }
						}),
						entry({
							id: 4,
							unit_key: 3,
							description: 'Amazon',
							display_description: { text: 'Amazon', from: 'description' }
						})
					]
				})
			]
		});

		expect(store.source.reveal?.(4)).toBe(true);

		await waitFor(() => {
			const selected = screen
				.getAllByRole('row')
				.filter((r) => r.getAttribute('aria-selected') === 'true');
			expect(selected).toHaveLength(2);
			expect(selected[0]).toHaveTextContent('Amazon');
		});
		expect(store.source.reveal?.(99)).toBe(false);
	});

	it('Enter without a cursor opens nothing; a click on a row opens its unit', async () => {
		await shown({ pending_review: [flow(7, 'REWE')] });

		await key('Enter');
		expect(unitPanel.open).not.toHaveBeenCalled();

		await fireEvent.click(screen.getByText('REWE'));
		expect(vi.mocked(unitPanel.open).mock.calls[0][0]).toBe(7);
	});
});

describe('ReviewQueue: needs an account and waiting', () => {
	function needing(id: number, currency: string) {
		return unit({
			...flow(id, `Out ${id}`),
			needs_account: { currency }
		});
	}
	function groupedQueue(
		units: ReturnType<typeof needing>[],
		groups: { currency: string; count: number }[],
		over = {}
	) {
		const base = queue({ needs_account: units });
		return {
			...base,
			sections: base.sections.map((s) =>
				s.kind === 'needs_account'
					? { ...s, groups, total: groups.reduce((n, g) => n + g.count, 0), ...over }
					: s
			)
		};
	}
	async function showGrouped(q: ReturnType<typeof groupedQueue>) {
		vi.mocked(getQueue).mockResolvedValue(q);
		const store = new ReviewQueueStore();
		await store.load();
		render(ReviewQueue, { props: { store, lookups, locale: 'en' } });
		return store;
	}

	it('groups the units by currency under headings with the server counts, singular and plural', async () => {
		await showGrouped(
			groupedQueue(
				[needing(1, 'USD'), needing(2, 'GBP'), needing(3, 'USD')],
				[
					{ currency: 'GBP', count: 1 },
					{ currency: 'USD', count: 3 }
				]
			)
		);

		const headings = [...document.querySelectorAll('[data-group]')].map(
			(h) => h.querySelector('[data-slot="band-label"]')!.textContent
		);
		expect(headings).toEqual([
			'A transfer needs an account in GBP',
			'3 transfers need an account in USD'
		]);
		// a band row among the rows of one card, not a heading, not a card of its own
		const usd = document.querySelector('[data-group="USD"]') as HTMLElement;
		expect(usd).toHaveAttribute('role', 'row');
		expect(usd.querySelector('[data-slot="subgroup-label"]')).toBeNull(); // a band row, not a subgroup row
		expect(usd).toHaveClass('sticky'); // beneath the header row while its units are in view
		expect(
			usd.closest('[data-section="needs_account"]')!.querySelectorAll('[role="grid"]')
		).toHaveLength(1);
		expect(within(usd).getByRole('button', { name: 'Add account' })).toBeInTheDocument();
		expect(document.querySelectorAll('h3')).toHaveLength(0);
		const after = [...usd.parentElement!.children]
			.slice([...usd.parentElement!.children].indexOf(usd) + 1)
			.filter((n) => n.getAttribute('role') === 'rowgroup');
		expect(after).toHaveLength(2); // the USD units follow, then the GBP ones lead

		expect(screen.getByRole('heading', { name: /Needs an account/ })).toHaveTextContent('(4)');
	});

	it('steps the cursor over the units only, a band row is never a stop', async () => {
		await showGrouped(
			groupedQueue(
				[needing(1, 'GBP'), needing(2, 'USD'), needing(3, 'USD')],
				[
					{ currency: 'GBP', count: 1 },
					{ currency: 'USD', count: 2 }
				]
			)
		);
		const cursorUnit = () =>
			document
				.querySelector('[data-unit] [aria-selected="true"]')
				?.closest('[data-unit]')
				?.getAttribute('data-unit');

		await key('j');
		expect(cursorUnit()).toBe('1');
		await key('j'); // across the USD band row to the next unit
		expect(cursorUnit()).toBe('2');
		await key('j');
		expect(cursorUnit()).toBe('3');
		await key('j');
		expect(cursorUnit()).toBe('3');
		expect(document.querySelectorAll('[role="row"][aria-selected="true"]')).toHaveLength(1);
	});

	it('opens the Add account dialog for the currency, kind cash, and says nothing moved after it', async () => {
		const open = vi.spyOn(accountDialog, 'openAdd').mockImplementation(() => {});
		const store = await showGrouped(
			groupedQueue([needing(1, 'USD'), needing(2, 'USD')], [{ currency: 'USD', count: 2 }])
		);
		expect(screen.queryByText(/can now be completed/)).toBeNull();

		await fireEvent.click(screen.getByRole('button', { name: 'Add account' }));

		const options = open.mock.calls[0][0]!;
		expect(options).toMatchObject({ currency: 'USD', kind: 'cash' });
		options.onadded!({} as never);
		await waitFor(() =>
			expect(screen.getByText('2 units can now be completed: refresh')).toBeInTheDocument()
		);
		expect(store.units.map((u) => u.anchor_entry_id)).toEqual([1, 2]);

		getQueue.mockClear();
		await fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
		await waitFor(() => expect(getQueue).toHaveBeenCalledTimes(1));
		await waitFor(() => expect(screen.queryByText(/can now be completed/)).toBeNull());
		open.mockRestore();
	});

	it('steps in the visual order: the units of a later page join their currency group', async () => {
		const first = groupedQueue(
			[needing(1, 'USD'), needing(2, 'EUR')],
			[
				{ currency: 'EUR', count: 2 },
				{ currency: 'USD', count: 2 }
			],
			{ next_cursor: 'c2' }
		);
		const store = await showGrouped(first);
		expect(store.units.map((u) => u.anchor_entry_id)).toEqual([2, 1]);

		const more = groupedQueue(
			[needing(3, 'EUR'), needing(4, 'USD')],
			[
				{ currency: 'EUR', count: 2 },
				{ currency: 'USD', count: 2 }
			]
		);
		getQueue.mockResolvedValue(more);
		await fireEvent.click(screen.getByRole('button', { name: 'Load more' }));

		await waitFor(() => expect(store.units).toHaveLength(4));
		const drawn = [...document.querySelectorAll('[data-unit]')].map((n) =>
			Number(n.getAttribute('data-unit'))
		);
		expect(drawn).toEqual([2, 3, 1, 4]);
		expect(store.units.map((u) => u.anchor_entry_id)).toEqual(drawn);
		expect(store.neighbour(2, 1)).toBe(3);
		expect(store.neighbour(3, 1)).toBe(1);
	});

	function waitingQueue(
		units: ReturnType<typeof unit>[],
		accountGroups: { account_id: number; synced_through: string | null; count: number }[]
	) {
		const base = queue({ waiting: units });
		return {
			...base,
			sections: base.sections.map((s) =>
				s.kind === 'waiting' ? { ...s, account_groups: accountGroups } : s
			)
		};
	}
	const waitingFor = (id: number, account_id: number, synced_through: string | null) =>
		unit({ ...flow(id, `Out ${id}`), waiting: { account_id, synced_through } });

	it('draws the waiting section as one card, a band row per account giving its reason once', async () => {
		vi.mocked(getQueue).mockResolvedValue(
			waitingQueue(
				[waitingFor(1, 2, '2026-10-12'), waitingFor(2, 1, null), waitingFor(3, 2, '2026-10-12')],
				[
					{ account_id: 1, synced_through: null, count: 1 },
					{ account_id: 2, synced_through: '2026-10-12', count: 2 }
				]
			)
		);
		const store = new ReviewQueueStore();
		await store.load();
		render(ReviewQueue, { props: { store, lookups, locale: 'en' } });

		const headings = [
			...document.querySelectorAll('[data-group-account] [data-slot="band-label"]')
		].map((h) => h.textContent!.trim());
		expect(headings).toHaveLength(2);
		expect(headings[0]).toBe('Waiting for Giro, not synced yet');
		expect(headings[1]).toMatch(/^Waiting for Savings, synced through .*12.*2026$/);
		expect(document.querySelectorAll('[data-slot="waiting-reason"]')).toHaveLength(0);
		const section = document.querySelector('[data-section="waiting"]')!;
		expect(section.querySelectorAll('[role="grid"]')).toHaveLength(1);
		expect(section.querySelectorAll('[role="row"][data-group-account]')).toHaveLength(2);
		expect(screen.queryByRole('button', { name: 'Add account' })).toBeNull(); // no action on a waiting group
		expect(screen.getByRole('heading', { name: /Waiting \(/ })).toHaveTextContent('(3)');
		// the units step in the order drawn: the account group first, then the next
		expect(store.units.map((u) => u.anchor_entry_id)).toEqual([2, 1, 3]);
		const drawn = [...section.querySelectorAll('[data-unit]')].map((n) =>
			Number(n.getAttribute('data-unit'))
		);
		expect(drawn).toEqual([2, 1, 3]);
	});
});

describe('ReviewQueue with an account filter', () => {
	it('says nothing matches and offers Clear filters, naming the accounts', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({}));
		const store = new ReviewQueueStore();
		await store.applyAccounts([2]);
		const onclearfilters = vi.fn();
		render(ReviewQueue, { props: { store, lookups, locale: 'en', onclearfilters } });

		expect(screen.getByText('No units match these filters')).toBeInTheDocument();
		expect(screen.getByText('Savings')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
		expect(onclearfilters).toHaveBeenCalledTimes(1);
	});

	it('keeps the sections and their own empty lines when something shows', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [flow(1, 'REWE')] }));
		const store = new ReviewQueueStore();
		await store.applyAccounts([1]);
		render(ReviewQueue, { props: { store, lookups, locale: 'en' } });

		expect(screen.queryByText('No units match these filters')).toBeNull();
		expect(screen.getByText('No transfer is missing an account.')).toBeInTheDocument();
	});
});

describe('ReviewQueue cut by counterparty', () => {
	const cpUnit = (id: number, text: string, key: string | null) => ({
		...flow(id, text),
		counterparty_key: key
	});
	const grp = (key: string | null, label: string | null, count: number, other = false) => ({
		key,
		label,
		count,
		other
	});
	async function byCounterparty(pending: ReturnType<typeof cpUnit>[], extra = {}) {
		vi.mocked(getQueue).mockResolvedValue(
			queue(
				{ pending_review: pending },
				{
					sections: queue({ pending_review: pending }).sections.map((s) =>
						s.kind === 'pending_review'
							? {
									...s,
									counterparty_groups: [
										grp('kometa', 'Versandhaus Kometa', 12),
										grp('rewe', 'REWE', 2),
										grp(null, null, 5, true)
									],
									...extra
								}
							: s
					)
				}
			)
		);
		const store = new ReviewQueueStore();
		await store.applyView([], 'counterparty');
		render(ReviewQueue, { props: { store, lookups, locale: 'en' } });
		return store;
	}
	const pendingCard = () => document.querySelector('[data-section="pending_review"]')!;

	it('draws a band per counterparty with its count, Other last, and the date column', async () => {
		await byCounterparty([
			cpUnit(1, 'a', 'kometa'),
			cpUnit(2, 'b', 'kometa'),
			cpUnit(3, 'c', 'rewe'),
			cpUnit(4, 'd', null)
		]);

		const bands = [...pendingCard().querySelectorAll('[data-slot="band-label"]')].map((n) =>
			n.textContent?.replace(/\s+/g, ' ').trim()
		);
		expect(bands).toEqual(['Versandhaus Kometa (12)', 'REWE (2)', 'Other (5)']);
		expect(pendingCard().querySelector('[data-month]')).toBeNull();
		expect(pendingCard().querySelector('[role="columnheader"][data-col="date"]')).not.toBeNull();
		expect(pendingCard().querySelector('[role="grid"]')).toHaveStyle('--sticky-offset: 3.75rem');
	});

	it('keeps by-date unchanged: month and day rows, no date column', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [flow(1, 'a')] }));
		const store = new ReviewQueueStore();
		await store.load();
		render(ReviewQueue, { props: { store, lookups, locale: 'en' } });

		expect(pendingCard().querySelector('[data-month]')).not.toBeNull();
		expect(pendingCard().querySelector('[data-col="date"]')).toBeNull();
	});

	it('continues the last band over a page boundary, without a second band or duplicates', async () => {
		const store = await byCounterparty([cpUnit(1, 'a', 'kometa'), cpUnit(2, 'b', 'kometa')], {
			next_cursor: 'c1',
			total: 4
		});
		vi.mocked(getQueue).mockResolvedValue({
			...queue(),
			sections: [
				section(
					'pending_review',
					[cpUnit(2, 'b', 'kometa'), cpUnit(3, 'c', 'kometa'), cpUnit(4, 'd', 'rewe')],
					{
						total: 4
					}
				),
				section('needs_account', []),
				section('waiting', [])
			]
		});
		await fireEvent.click(screen.getAllByRole('button', { name: 'Load more' })[0]);
		await waitFor(() => expect(store.units).toHaveLength(4));

		const bands = [...pendingCard().querySelectorAll('[data-slot="band-label"]')].map((n) =>
			n.textContent?.replace(/\s+/g, ' ').trim()
		);
		expect(bands).toEqual(['Versandhaus Kometa (12)', 'REWE (2)']);
		expect(
			[...pendingCard().querySelectorAll('[data-unit]')].map((n) => n.getAttribute('data-unit'))
		).toEqual(['1', '2', '3', '4']);
	});

	it('moves the cursor and opens units in the drawn order, across bands', async () => {
		await byCounterparty([cpUnit(1, 'a', 'kometa'), cpUnit(2, 'b', 'rewe')]);

		await key('j');
		await key('j');
		await key('Enter');

		expect(unitPanel.open).toHaveBeenCalledWith(2, expect.anything());
	});
});

describe('ReviewQueue: units committed as seen', () => {
	const boxes = () => screen.getAllByRole('checkbox') as HTMLInputElement[];
	const unitBox = (anchor: number) =>
		document.querySelector<HTMLInputElement>(`[data-unit="${anchor}"] input[type="checkbox"]`);

	const TEXTS: Record<number, string> = { 1: 'REWE', 2: 'Edeka' };
	function serve() {
		const same = (id: number) => flow(id, TEXTS[id]);
		api.getUnit.mockImplementation(async (id: number) => same(id));
		api.previewUnit.mockImplementation(async (d: { anchor_entry_id: number }) =>
			preview(same(d.anchor_entry_id))
		);
		api.commitUnit.mockImplementation(async (d: { anchor_entry_id: number }) =>
			committed(same(d.anchor_entry_id))
		);
	}

	it("has a checkbox column in the pending section only, on a unit's first row", async () => {
		await shown({
			pending_review: [
				flow(1, 'REWE'),
				unit({
					anchor_entry_id: 2,
					entries: [entry({ id: 2, unit_key: 2 }), entry({ id: 3, unit_key: 2 })]
				})
			],
			waiting: [flow(5, 'Edeka')]
		});
		expect(boxes()).toHaveLength(2);
		expect(unitBox(2)!.closest('[role="row"]')).toHaveAttribute('data-entry-id', '2');
		expect(
			document.querySelectorAll('[data-section="waiting"] input[type="checkbox"]')
		).toHaveLength(0);
		expect(
			document.querySelectorAll('[data-section="pending_review"] [data-col="select"]')
		).toHaveLength(
			4 // the header and the three rows
		);
	});

	it('disables a checkbox where a commit would not confirm, with the reason as tooltip', async () => {
		await shown({
			pending_review: [
				flow(1, 'REWE', { model_pending: true }),
				flow(2, 'Edeka', { category_id: null, review_flags: ['unclassified'] }),
				flow(3, 'Aldi')
			]
		});
		expect(unitBox(1)).toBeDisabled();
		expect(unitBox(1)!.parentElement).toHaveAttribute('title', 'The model is still looking');
		expect(unitBox(2)).toBeDisabled();
		expect(unitBox(2)!.parentElement).toHaveAttribute('title', 'No category yet');
		expect(unitBox(3)).toBeEnabled();
	});

	it('ticks with the checkbox without opening the panel, and shows the footer with the count', async () => {
		await shown({ pending_review: [flow(1, 'REWE'), flow(2, 'Edeka')] });
		expect(document.querySelector('[data-slot="selection-footer"]')).toBeNull();

		await fireEvent.click(unitBox(1)!);
		expect(unitPanel.open).not.toHaveBeenCalled();
		const footer = document.querySelector<HTMLElement>('[data-slot="selection-footer"]')!;
		expect(footer).toHaveTextContent('1 unit selected');
		await fireEvent.click(unitBox(2)!);
		expect(footer).toHaveTextContent('2 units selected');

		await fireEvent.click(within(footer).getByRole('button', { name: 'Clear' }));
		expect(document.querySelector('[data-slot="selection-footer"]')).toBeNull();
		expect(unitBox(1)!.checked).toBe(false);
	});

	it('ticks and clears the unit under the cursor with x, and says why it cannot', async () => {
		const store = await shown({
			pending_review: [flow(1, 'REWE'), flow(2, 'Edeka', { model_pending: true })]
		});
		await key('j');
		await key('x');
		expect(unitBox(1)!.checked).toBe(true);
		await key('x');
		expect(unitBox(1)!.checked).toBe(false);

		await key('j');
		await key('x');
		expect(store.selected.size).toBe(0);
		expect(store.notice).toBe('The model is still looking');
	});

	it('has a tri-state checkbox on a counterparty band, none on a day band', async () => {
		const cp = (id: number, key: string) => ({ ...flow(id, `u${id}`), counterparty_key: key });
		const store = await shown(
			{
				pending_review: [
					cp(1, 'rewe'),
					cp(2, 'rewe'),
					{ ...flow(3, 'u3', { model_pending: true }), counterparty_key: 'rewe' }
				]
			},
			{}
		);
		expect(document.querySelectorAll('[data-month] input, [data-day] input')).toHaveLength(3);
		await store.applyView([], 'counterparty');
		await waitFor(() => expect(document.querySelector('[data-counterparty]')).not.toBeNull());
		const band = document.querySelector<HTMLInputElement>(
			'[data-counterparty="rewe"] [role="row"] input'
		)!;
		expect(band.checked).toBe(false);

		await fireEvent.click(unitBox(1)!);
		await waitFor(() => expect(band.indeterminate).toBe(true));

		await fireEvent.click(band); // ticks the enabled units of the band, not the model's
		expect([...store.selected.keys()].sort()).toEqual([1, 2]);
		await waitFor(() => expect(band.checked).toBe(true));
		expect(band.indeterminate).toBe(false);

		await fireEvent.click(band);
		expect(store.selected.size).toBe(0);
	});

	it('commits the ticked units on Ctrl/⌘ + Enter with the panel closed, and says how it went', async () => {
		serve();
		const store = await shown({ pending_review: [flow(1, 'REWE'), flow(2, 'Edeka')] });
		await key('x'); // nothing under the cursor yet
		await fireEvent.click(unitBox(1)!);
		await fireEvent.click(unitBox(2)!);

		await fireEvent.keyDown(document.body, { key: 'Enter', ctrlKey: true });
		await waitFor(() => expect(store.notice).toBe('2 committed'));
		expect(api.commitUnit).toHaveBeenCalledTimes(2);
		expect(unitPanel.open).not.toHaveBeenCalled();
		expect(document.querySelector('[data-slot="selection-footer"]')).toBeNull();
		expect(document.querySelector('[data-entry-id="1"]')).toHaveAttribute('data-resolved');
	});

	it('commits with the footer button too', async () => {
		serve();
		const store = await shown({ pending_review: [flow(1, 'REWE')] });
		await fireEvent.click(unitBox(1)!);
		await fireEvent.click(screen.getByRole('button', { name: 'Commit' }));
		await waitFor(() => expect(store.notice).toBe('1 committed'));
	});

	it('leaves Ctrl/⌘ + Enter to the panel while it is open', async () => {
		serve();
		const store = await shown({ pending_review: [flow(1, 'REWE')] });
		await fireEvent.click(unitBox(1)!);
		(unitPanel as unknown as { isOpen: boolean }).isOpen = true;
		try {
			await fireEvent.keyDown(document.body, { key: 'Enter', metaKey: true });
			expect(api.commitUnit).not.toHaveBeenCalled();
			expect(store.selected.size).toBe(1);
		} finally {
			(unitPanel as unknown as { isOpen: boolean }).isOpen = false;
		}
	});

	it('marks a unit that changed, with the reason, and leaves it unticked', async () => {
		serve();
		api.previewUnit.mockImplementation(async (d: { anchor_entry_id: number }) => {
			const answer = preview(flow(d.anchor_entry_id, TEXTS[d.anchor_entry_id]));
			answer.rows[0].description = 'Changed text';
			return answer;
		});
		const store = await shown({ pending_review: [flow(1, 'REWE')] });
		await fireEvent.click(unitBox(1)!);
		await fireEvent.keyDown(document.body, { key: 'Enter', ctrlKey: true });
		await waitFor(() => expect(store.notice).toBe('0 committed · 1 not committed'));
		const row = document.querySelector('[data-entry-id="1"]')!;
		expect(row).toHaveAttribute('data-changed');
		expect(row).toHaveAttribute(
			'title',
			'Changed since you saw it: description is now Changed text'
		);
		expect(unitBox(1)!.checked).toBe(false);
	});
});
