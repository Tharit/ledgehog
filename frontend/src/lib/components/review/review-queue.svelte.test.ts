import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { account, category, entry, payee } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { ReviewQueueStore } from '#lib/stores/review-queue.svelte.js';
import { apiError, queue, section, unit } from '#lib/units/fixtures.js';
import { unitPanel } from '#lib/units/panel-instance.js';
import { activeUnitSource } from '#lib/units/sources.js';
import ReviewQueue from './review-queue.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	getQueue: vi.fn(),
	getNewUnitCount: vi.fn(),
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
});

describe('ReviewQueue', () => {
	it('has three headed sections with their counts, and empty ones say what belongs there', async () => {
		await shown({ pending_review: [flow(1, 'REWE'), flow(2, 'Edeka')] });

		const pending = screen.getByRole('heading', { name: /Pending review/ });
		expect(pending).toHaveTextContent('(2)');
		expect(screen.getByRole('heading', { name: /Needs an account/ })).toHaveTextContent('(0)');
		expect(screen.getByRole('heading', { name: /Waiting/ })).toHaveTextContent('(0)');
		expect(screen.getAllByText(/A transfer whose counter account does not exist/)).toHaveLength(1);
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
						entry({ id: 1, unit_key: 1, display_text: 'Amazon' }),
						entry({ id: 2, unit_key: 1, display_text: 'Amazon' })
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
							display_text: 'Out',
							counterpart_entry_id: 4
						}),
						entry({
							id: 4,
							unit_key: 3,
							type: 'transfer',
							account_id: 2,
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
						entry({ id: 1, unit_key: 1, display_text: 'Amazon' }),
						entry({ id: 2, unit_key: 1, display_text: 'Amazon' })
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
						entry({ id: 3, unit_key: 3, display_text: 'Amazon' }),
						entry({ id: 4, unit_key: 3, display_text: 'Amazon' })
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
