import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { account, category, entry, payee } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { changes } from '#lib/stores/changes.svelte.js';
import { ReviewQueueStore } from '#lib/stores/review-queue.svelte.js';
import { apiError, queue, section, unit } from '#lib/units/fixtures.js';
import { unitPanel } from '#lib/units/panel-instance.js';
import { activeUnitSource } from '#lib/units/sources.js';
import { accounts as accountDialog } from '#lib/accounts/controller.svelte.js';
import ReviewQueue from './review-queue.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	getQueue: vi.fn(),
	listRules: vi.fn()
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
				display_text: text,
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
	it('marks a unit the model is still looking at, and no other', async () => {
		await shown({
			pending_review: [{ ...flow(1, 'REWE'), model_pending: true }, flow(2, 'Edeka')]
		});

		const marks = screen.getAllByRole('img', { name: 'The model is still looking at this' });
		expect(marks).toHaveLength(1);
		expect(marks[0]).toHaveAttribute('title', 'The model is still looking at this');
		expect(marks[0].closest('[data-unit]')).toHaveAttribute('data-unit', '1');
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
		await shown({ pending_review: [{ ...flow(1, 'REWE'), model_pending: true }] });
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
						entry({ id: 1, unit_key: 1, description: 'Amazon', display_text: 'Amazon' }),
						entry({ id: 2, unit_key: 1, description: 'Amazon', display_text: 'Amazon' })
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
							display_text: 'Out',
							counterpart_entry_id: 4
						}),
						entry({
							id: 4,
							unit_key: 3,
							type: 'transfer',
							account_id: 2,
							description: 'In',
							display_text: 'In',
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
				expect(row.className).toContain('group-hover/unit:bg-muted');
		}
		expect(groups[2].className).not.toContain('group/unit');
		const markers = document.querySelectorAll('[data-unit-marker]');
		expect(markers).toHaveLength(1);
		expect(groups[0].querySelector('[data-entry-id="1"]')!.contains(markers[0])).toBe(true);
		expect(markers[0].getAttribute('title')).toMatch(/^Split total .*5\.00/);
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
		expect(getQueue).toHaveBeenLastCalledWith({ section: 'pending_review', cursor: 'c1' });
		expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
	});
});

describe('ReviewQueue: marks after a commit', () => {
	const again = (id: number, text: string, flags: string[] = ['unconfirmed']) =>
		entry({
			id,
			unit_key: id,
			description: text,
			display_text: text,
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
						entry({ id: 1, unit_key: 1, description: 'Amazon', display_text: 'Amazon' }),
						entry({ id: 2, unit_key: 1, description: 'Amazon', display_text: 'Amazon' })
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
						entry({ id: 3, unit_key: 3, description: 'Amazon', display_text: 'Amazon' }),
						entry({ id: 4, unit_key: 3, description: 'Amazon', display_text: 'Amazon' })
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

		const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
		expect(headings).toEqual([
			'A transfer needs an account in GBP',
			'3 transfers need an account in USD'
		]);
		const usd = document.querySelector('[data-group="USD"]')!.nextElementSibling as HTMLElement;
		expect(within(usd).getAllByRole('rowgroup')).toHaveLength(2);
		expect(screen.getByRole('heading', { name: /Needs an account/ })).toHaveTextContent('(4)');
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

	it('gives a waiting unit its reason in one line, and the unit stays a plain row', async () => {
		await shown({
			waiting: [
				unit({ ...flow(1, 'Out'), waiting: { account_id: 2, synced_through: '2026-10-12' } }),
				unit({ ...flow(2, 'Out 2'), waiting: { account_id: 2, synced_through: null } })
			]
		});

		const reasons = [...document.querySelectorAll('[data-slot="waiting-reason"]')].map((n) =>
			n.textContent!.trim()
		);
		expect(reasons).toHaveLength(2);
		expect(reasons[0]).toMatch(/^Waiting for Savings, synced through .*12.*2026$/);
		expect(reasons[1]).toBe('Waiting for Savings, not synced yet');
		expect(screen.getByRole('heading', { name: /Waiting/ })).toHaveTextContent('(2)');
	});

	it('gives a unit waiting for the rest of an order its line', async () => {
		await shown({
			waiting: [
				unit({
					...flow(1, 'Out', { review_flags: ['unconfirmed', 'waiting'] }),
					waiting_order: {
						order: '302-1',
						provider: 'amazon',
						charged: { amount: -3000, currency: 'EUR' },
						total: { amount: -5000, currency: 'EUR' }
					}
				})
			]
		});

		const lines = [...document.querySelectorAll('[data-slot="waiting-order-reason"]')].map((n) =>
			n.textContent!.trim()
		);
		expect(lines).toEqual([
			'Waiting for the rest of order 302-1 from amazon: 20.00 of 50.00 not yet charged'
		]);
	});

	it('gives a unit waiting for a document its line, and the badges stay on the row', async () => {
		await shown({
			waiting: [
				unit({
					...flow(1, 'Out', { review_flags: ['unconfirmed', 'waiting'] }),
					waiting_document: { provider: 'amazon', covered_through: '2026-10-12' }
				}),
				unit({
					...flow(2, 'Out 2'),
					waiting_document: { provider: 'amazon', covered_through: null }
				})
			],
			pending_review: [
				unit(flow(3, 'Suggested', { review_flags: ['unconfirmed', 'document_suggested'] }))
			]
		});

		const lines = [...document.querySelectorAll('[data-slot="waiting-document-reason"]')].map((n) =>
			n.textContent!.trim()
		);
		expect(lines).toHaveLength(2);
		expect(lines[0]).toMatch(/^Waiting for a document from amazon, covered through .*12.*2026$/);
		expect(lines[1]).toBe('Waiting for a document from amazon, not synced yet');
		expect(document.querySelector('[data-flag="waiting"]')).not.toBeNull();
		expect(document.querySelector('[data-flag="document_suggested"]')).not.toBeNull();
	});
});
