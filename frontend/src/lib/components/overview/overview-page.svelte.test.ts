import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { account, category } from '#lib/ledger/fixtures.js';
import { byCategory, line, overview } from '#lib/reports/fixtures.js';
import { changes } from '#lib/stores/changes.svelte.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { reviewCount } from '#lib/stores/review-count.svelte.js';
import Page from '../../../routes/+page.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	getOverview: vi.fn(),
	getByCategory: vi.fn(),
	readChanges: vi.fn(),
	setChangesListener: vi.fn(),
	listAccounts: vi.fn(),
	listCategories: vi.fn(),
	listPayees: vi.fn(),
	listTags: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((res) => (resolve = res));
	return { promise, resolve };
}

/** a poll of the change watcher that finds the ledger at this value */
async function pollLedger(ledger: string): Promise<void> {
	api.readChanges.mockResolvedValue({ ledger, documents: 'b:1', accounts: {}, active_task: null });
	await changes.read();
}

beforeEach(async () => {
	vi.resetAllMocks();
	lookupsStore.reset();
	reviewCount.reset();
	reviewCount.known = true;
	api.readChanges.mockResolvedValue({
		ledger: 'b:1',
		documents: 'b:1',
		accounts: {},
		active_task: null
	});
	changes.start();
	await changes.read();
	api.listAccounts.mockResolvedValue([]);
	api.listCategories.mockResolvedValue([
		category({ id: 10, name: 'Housing', color: 'forest', icon: 'house' })
	]);
	api.listPayees.mockResolvedValue([]);
	api.listTags.mockResolvedValue([]);
	api.getOverview.mockResolvedValue(overview());
	api.getByCategory.mockResolvedValue(
		byCategory({ slices: [{ category_id: 10, total: line(-98000) }] })
	);
});

afterEach(() => changes.stop());

describe('the Overview page', () => {
	it('is titled "Overview" and described with the day, with no primary action', async () => {
		render(Page);

		expect(screen.getByRole('heading', { level: 1, name: 'Overview' })).toBeInTheDocument();
		expect(await screen.findByText('Tuesday, October 20, 2026')).toBeInTheDocument();
		expect(screen.queryByRole('button')).toBeNull();
	});

	it('shows skeletons on the first load and the figures once the answer arrives', async () => {
		const first = deferred<ReturnType<typeof overview>>();
		api.getOverview.mockReturnValue(first.promise);
		render(Page);

		expect(document.querySelectorAll('[data-slot="figure-skeleton"]').length).toBeGreaterThan(0);
		expect(document.querySelector('[data-slot="accounts-skeleton"]')).not.toBeNull();

		first.resolve(overview());
		expect(await screen.findByText('128,450.00 EUR')).toBeInTheDocument();
		expect(document.querySelector('[data-slot="accounts-skeleton"]')).toBeNull();
	});

	it('lays out four figure cards and the two half-width ones, the four wrapping 2 by 2 when narrow', async () => {
		render(Page);
		await screen.findByText('128,450.00 EUR');

		const figures = document.querySelector('[data-slot="figure-cards"]')!;
		expect(figures.children).toHaveLength(4);
		expect(figures).toHaveClass('sm:grid-cols-2', 'xl:grid-cols-4');
		const half = document.querySelector('[data-slot="half-cards"]')!;
		expect(half.children).toHaveLength(2);
		for (const name of ['Net worth', 'Savings rate', 'Spend', 'To review', 'Data age']) {
			expect(screen.getByRole('region', { name })).toBeInTheDocument();
		}
		expect(
			screen.getByRole('region', { name: 'Top expense categories, October so far' })
		).toBeInTheDocument();
	});

	it('lists the synced and the hand-kept accounts apart, in the order the server sent, with a link to all', async () => {
		api.getOverview.mockResolvedValue(
			overview({
				data_age: {
					synced: [
						{ ...account({ id: 7, name: 'Giro' }), data_age_days: 9 },
						{ ...account({ id: 3, name: 'Card' }), data_age_days: 2 }
					],
					by_hand: [{ ...account({ id: 5, name: 'Cash', synced: false }), data_age_days: null }],
					accounts: 12
				}
			})
		);
		render(Page);

		const card = await screen.findByRole('region', { name: 'Data age' });
		expect(card).toHaveTextContent('Stalest first');
		const synced = within(await screen.findByRole('list', { name: 'Synced' }));
		expect(synced.getAllByRole('link').map((a) => a.getAttribute('href'))).toEqual([
			'/accounts/7',
			'/accounts/3'
		]);
		const byHand = within(screen.getByRole('list', { name: 'By hand' }));
		expect(byHand.getAllByRole('link').map((a) => a.getAttribute('href'))).toEqual(['/accounts/5']);
		expect(screen.getByRole('link', { name: /All 12 accounts/ })).toHaveAttribute(
			'href',
			'/accounts'
		);
	});

	it('leaves out a list with no accounts', async () => {
		render(Page);

		await screen.findByRole('list', { name: 'Synced' });
		expect(screen.queryByRole('list', { name: 'By hand' })).toBeNull();
		expect(screen.getByRole('link', { name: /All 1 account\b/ })).toBeInTheDocument();
	});

	it('says "open n d" of an open clearance account and "settled" of a settled one', async () => {
		api.getOverview.mockResolvedValue(
			overview({
				data_age: {
					synced: [],
					by_hand: [
						{
							...account({
								id: 8,
								name: 'Amazon',
								kind: 'clearance',
								synced: false,
								last_data_on: '2026-10-10',
								balance: { amount: -4000, currency: 'EUR' }
							}),
							data_age_days: 10
						},
						{
							...account({
								id: 9,
								name: 'Zalando',
								kind: 'clearance',
								synced: false,
								last_data_on: '2026-09-01',
								balance: { amount: 0, currency: 'EUR' }
							}),
							data_age_days: 49
						}
					],
					accounts: 2
				}
			})
		);
		render(Page);

		const list = within(await screen.findByRole('list', { name: 'By hand' }));
		expect(list.getByText('open 10 d')).toBeInTheDocument();
		expect(list.getByText('settled')).toBeInTheDocument();
	});

	it('shows the To review card from the Review item count', async () => {
		reviewCount.pendingReview = 4;
		reviewCount.needsAccount = 1;
		reviewCount.count = 5;
		reviewCount.known = true;
		render(Page);

		const card = await screen.findByRole('region', { name: 'To review' });
		expect(card).toHaveTextContent('5');
		expect(card).toHaveTextContent(/Ready to review\s*4/);
		expect(card).toHaveTextContent(/Needs an account\s*1/);
	});

	it('draws the top categories with the names the shared lists hold', async () => {
		render(Page);

		const row = await waitFor(() => {
			const found = document.querySelector<HTMLElement>('[data-category="10"]');
			expect(found).not.toBeNull();
			return found!;
		});
		await waitFor(() => expect(row).toHaveTextContent('Housing'));
		expect(api.getByCategory).toHaveBeenCalledWith(
			expect.objectContaining({ kind: 'expense', top: 5 })
		);
	});

	it('says "No accounts yet" with a way to Accounts when there are none', async () => {
		api.getOverview.mockResolvedValue(
			overview({ data_age: { synced: [], by_hand: [], accounts: 0 } })
		);
		render(Page);

		expect(await screen.findByText('No accounts yet')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Open Accounts' })).toHaveAttribute(
			'href',
			'/accounts'
		);
		expect(screen.queryByRole('region', { name: 'Net worth' })).toBeNull();
	});

	it('says so when the first read fails, and reads again on "Try again"', async () => {
		api.getOverview.mockRejectedValueOnce(new Error('offline'));
		render(Page);

		expect(await screen.findByText('The overview could not be loaded')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(await screen.findByText('128,450.00 EUR')).toBeInTheDocument();
	});
});

describe('the Overview page is a computed view', () => {
	it('reads again when the ledger moves, keeps its figures on screen meanwhile and replaces them when the answer arrives', async () => {
		render(Page);
		expect(await screen.findByText('128,450.00 EUR')).toBeInTheDocument();
		expect(api.getOverview).toHaveBeenCalledTimes(1);

		const next = deferred<ReturnType<typeof overview>>();
		api.getOverview.mockReturnValue(next.promise);
		await pollLedger('b:2');
		await waitFor(() => expect(api.getOverview).toHaveBeenCalledTimes(2));

		// nothing is blanked, no skeleton, no "New data" notice: the old figures stand
		expect(screen.getByText('128,450.00 EUR')).toBeInTheDocument();
		expect(document.querySelector('[data-slot="figure-skeleton"]')).toBeNull();
		expect(screen.queryByText(/New data/)).toBeNull();

		next.resolve(
			overview({
				net_worth: { ...overview().net_worth, total: { amount: 13000000, currency: 'EUR' } }
			})
		);
		expect(await screen.findByText('130,000.00 EUR')).toBeInTheDocument();
		expect(screen.queryByText('128,450.00 EUR')).toBeNull();
	});

	it('does not read again when a poll finds the ledger unchanged', async () => {
		render(Page);
		await screen.findByText('128,450.00 EUR');

		await pollLedger('b:1');

		expect(api.getOverview).toHaveBeenCalledTimes(1);
	});
});
