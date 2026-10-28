import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import {
	balances,
	byCategoryTree,
	overTimeCategories,
	overTimeSavings,
	reportLookups
} from '#lib/reports/trend-fixtures.js';
import type { Scope } from '#lib/reports/links.js';
import { dimensionVars } from '#lib/theme/dimensions.js';
import BalancesView from './balances-view.svelte';
import ByCategoryView from './by-category-view.svelte';
import OverTimeView from './over-time-view.svelte';

const { categories, accounts } = reportLookups();
/** The tile that draws an icon: its glyph's wrapper, with the colour it was given. */
function tileOf(within: Element | null, icon: string): HTMLElement | null {
	const glyph = within?.querySelector(`.lucide-${icon}`);
	return (glyph?.parentElement as HTMLElement | null) ?? null;
}

function expectStone(tile: HTMLElement | null) {
	expect(tile).not.toBeNull();
	expect(tile!.style.getPropertyValue('--tile-fg')).toBe(dimensionVars('stone').fg);
}

const scope: Scope = { from: '2026-10-01', to: '2026-10-31', accountIds: [], tagIds: [] };

function hrefOf(row: HTMLElement): string | null {
	return row.querySelector('a')?.getAttribute('href') ?? null;
}

describe('ByCategoryView', () => {
	const rowsOf = (table: HTMLElement) =>
		[...table.querySelectorAll('tbody:not([data-slot]) tr')].map((tr) =>
			tr.getAttribute('data-category')
		);

	it('lists the category tree with every amount linking to the ledger', async () => {
		const { container } = render(ByCategoryView, {
			props: { report: byCategoryTree(), categories, scope }
		});

		const table = container.querySelector('[data-slot="category-table"]') as HTMLElement;
		await fireEvent.click(screen.getByRole('button', { name: 'Expand Food' }));
		const food = table.querySelector('[data-category="1"][data-itself="false"]') as HTMLElement;
		expect(hrefOf(food)).toBe('/ledger?from=2026-10-01&to=2026-10-31&category_id=1');
		const itself = table.querySelector('[data-itself="true"]') as HTMLElement;
		expect(hrefOf(itself)).toBe(
			'/ledger?from=2026-10-01&to=2026-10-31&category_id=1&category_descendants=false'
		);
		expect(table.querySelector('[data-category="4"]')).toBeInTheDocument();
	});

	it('opens collapsed to the top level; a group row expands and collapses its children', async () => {
		const { container } = render(ByCategoryView, {
			props: { report: byCategoryTree(), categories, scope }
		});
		const table = container.querySelector('[data-slot="category-table"]') as HTMLElement;

		// Home, Food and Refunds only: no "(itself)", no Groceries or Eating out
		expect(rowsOf(table)).toEqual(['4', '1', '6']);
		const toggle = screen.getByRole('button', { name: 'Expand Food' });
		expect(toggle).toHaveAttribute('aria-expanded', 'false');
		// a category without children has no toggle
		expect(screen.queryByRole('button', { name: /Expand Home/ })).toBeNull();
		// the group's figure is its whole, a link
		expect(table.querySelector('[data-category="1"] a')).toHaveAttribute(
			'href',
			'/ledger?from=2026-10-01&to=2026-10-31&category_id=1'
		);

		// a real button: focusable, and Enter and Space activate it natively
		toggle.focus();
		expect(document.activeElement).toBe(toggle);
		await fireEvent.click(toggle);
		expect(rowsOf(table)).toEqual(['4', '1', '1', '2', '3', '6']);
		expect(screen.getByRole('button', { name: 'Collapse Food' })).toHaveAttribute(
			'aria-expanded',
			'true'
		);

		await fireEvent.click(screen.getByRole('button', { name: 'Collapse Food' }));
		expect(rowsOf(table)).toEqual(['4', '1', '6']);
	});

	it('names the category of the other sign in a note rather than drawing it', () => {
		render(ByCategoryView, { props: { report: byCategoryTree(), categories, scope } });

		const note = screen.getByText(/Not in the chart/).closest('p')!;
		expect(note).toHaveTextContent('Refunds');
		expect(screen.queryByText('Refunds', { selector: '[data-slice] *' })).toBeNull();
	});

	it('writes the legend as colour and name only, with "Other", and no amounts', () => {
		const { container } = render(ByCategoryView, {
			props: { report: byCategoryTree(), categories, scope }
		});

		const other = container.querySelector('[data-slice="other"]')!;
		expect(other).toHaveTextContent(/^Other$/);
		const legend = container.querySelector('[data-slot="donut-legend"]')!;
		expect(legend.querySelector('a')).toBeNull();
		for (const item of legend.querySelectorAll('li')) {
			expect(item.textContent).not.toMatch(/\d/);
		}
	});

	it('draws each legend entry as its category’s icon tile, "Other" as circle-ellipsis', () => {
		const { container } = render(ByCategoryView, {
			props: { report: byCategoryTree(), categories, scope }
		});

		const legend = container.querySelector('[data-slot="donut-legend"]')!;
		for (const item of legend.querySelectorAll('li')) {
			expect(item.querySelector('span[style] svg')).toBeInTheDocument();
		}
		const food = legend.querySelector('[data-slice="c1"] span[style]')!;
		expect(food.getAttribute('style')).toContain('--dim-sage');
		expect(
			legend.querySelector('[data-slice="other"] .lucide-circle-ellipsis')
		).toBeInTheDocument();
		expect(legend.querySelector('.rounded-\\[2px\\]')).toBeNull();
	});

	it('gives the donut an explicit width, or its grid cell collapses it to nothing', () => {
		const { container } = render(ByCategoryView, {
			props: { report: byCategoryTree(), categories, scope }
		});

		// jsdom has no layout; the collapse (auto margins + a width: 100% child) is a class matter.
		const donut = container.querySelector('[data-slot="category-donut"]')!;
		expect(donut).toHaveClass('w-full', 'max-w-64', 'aspect-square');
	});

	it('beneath it, what is not in the categories above, each a link', () => {
		const { container } = render(ByCategoryView, {
			props: { report: byCategoryTree(), categories, scope }
		});

		const side = container.querySelector('[data-slot="not-in-categories"]') as HTMLElement;
		expect(within(side).getByText('Unclassified, out')).toBeInTheDocument();
		expect(side.querySelector('[data-line="unclassified-out"] a')).toHaveAttribute(
			'href',
			'/ledger?from=2026-10-01&to=2026-10-31&uncategorised=true&direction=out'
		);
		expect(side.querySelector('[data-line="unconfirmed"] a')).toHaveAttribute(
			'href',
			'/ledger?from=2026-10-01&to=2026-10-31&flag=unconfirmed'
		);
		// tabular: the count in the Entries column, the amount in the Amount column, the rest empty
		const unconfirmed = side.querySelector('[data-line="unconfirmed"]') as HTMLElement;
		expect(unconfirmed.querySelectorAll('td')[0]).toHaveTextContent(/^3$/);
		expect(unconfirmed.querySelectorAll('td')[1]).toBeEmptyDOMElement();
		expect(unconfirmed.querySelector('a')).toHaveAccessibleName('3 entries not yet confirmed');
		const out = side.querySelector('[data-line="unclassified-out"]') as HTMLElement;
		expect(out.querySelectorAll('td')).toHaveLength(4);
		expect(out.querySelectorAll('td')[0]).toHaveTextContent(/^\d+$/);
		expect(side.querySelector('th[scope="colgroup"]')).toHaveTextContent(
			'Not in the categories above'
		);
	});

	it('leads the total and the not-in-the-categories rows with their measure’s stone tile', () => {
		const { container } = render(ByCategoryView, {
			props: { report: byCategoryTree(), categories, scope }
		});
		const table = container.querySelector('[data-slot="category-table"]') as HTMLElement;

		expectStone(tileOf(table.querySelector('[data-slot="category-total"] th'), 'receipt'));
		const line = (key: string) => table.querySelector(`[data-line="${key}"] th`);
		expectStone(tileOf(line('unclassified-out'), 'circle-question-mark'));
		expectStone(tileOf(line('unclassified-in'), 'circle-question-mark'));
		expectStone(tileOf(line('reconciliations'), 'scale'));
		expectStone(tileOf(line('unconfirmed'), 'inbox'));
		// an "(itself)" row sits under its parent's tile and has none of its own
		expect(table.querySelector('[data-itself="true"] th [class*="size-6"]')).toBeNull();
	});

	it('says so when the period has nothing', () => {
		render(ByCategoryView, {
			props: {
				report: byCategoryTree({
					categories: [],
					slices: [],
					other: null,
					unclassified_out: { total: { amount: 0, currency: 'EUR' }, count: 0, unvalued: [] },
					reconciliations: { total: { amount: 0, currency: 'EUR' }, count: 0, unvalued: [] },
					unconfirmed_count: 0
				}),
				categories,
				scope
			}
		});

		expect(screen.getByText(/Nothing in this period/)).toBeInTheDocument();
	});
});

describe('OverTimeView, income and expense', () => {
	it('has a row per figure, links where a figure is a sum of entries and not for savings', () => {
		const { container } = render(OverTimeView, {
			props: { report: overTimeSavings(), categories, scope }
		});

		const row = (key: string) => container.querySelector(`[data-row="${key}"]`) as HTMLElement;
		expect(
			[...container.querySelectorAll('[data-slot="savings-table"] tbody tr')].map((tr) =>
				tr.getAttribute('data-row')
			)
		).toEqual(['income', 'expense', 'unclassified', 'reconciliations', 'savings', 'rate']);
		expect(row('income').querySelector('a')).toHaveAttribute(
			'href',
			'/ledger?from=2026-08-01&to=2026-08-31&category_id=5'
		);
		expect(row('savings').querySelector('a')).toBeNull();
		expect(row('rate').querySelector('a')).toBeNull();
		expect(row('rate')).toHaveTextContent('58%');
		// the rate of an incomplete period carries the marker
		expect(row('rate').querySelector('[data-slot="incomplete-marker"]')).not.toBeNull();
		expect(screen.getByRole('columnheader', { name: 'Total' })).toBeInTheDocument();
	});

	it('leads each row with its measure’s stone tile', () => {
		const { container } = render(OverTimeView, {
			props: { report: overTimeSavings(), categories, scope }
		});

		const icons = {
			income: 'hand-coins',
			expense: 'receipt',
			unclassified: 'circle-question-mark',
			reconciliations: 'scale',
			savings: 'piggy-bank',
			rate: 'percent'
		};
		for (const [key, icon] of Object.entries(icons)) {
			const row = container.querySelector(`[data-slot="savings-table"] [data-row="${key}"] th`);
			expectStone(tileOf(row, icon));
		}
	});

	it('draws the chart at a fixed height, not an aspect ratio', () => {
		const { container } = render(OverTimeView, {
			props: { report: overTimeSavings(), categories, scope }
		});

		const chart = container.querySelector('[data-slot="income-expense-chart"]')!;
		expect(chart).toHaveClass('h-72', 'aspect-auto');
	});
});

describe('OverTimeView, by category', () => {
	it('opens collapsed to the top level and expands a group like the tree in Settings', async () => {
		const { container } = render(OverTimeView, {
			props: { report: overTimeCategories(), categories, scope }
		});

		const table = container.querySelector('[data-slot="category-trend-table"]') as HTMLElement;
		expect(table.querySelectorAll('tbody tr')).toHaveLength(2);
		expect(table.querySelector('[data-category="2"]')).toBeNull();

		await fireEvent.click(screen.getByRole('button', { name: 'Expand Food' }));
		expect(table.querySelectorAll('tbody tr')).toHaveLength(4);
		await fireEvent.click(screen.getByRole('button', { name: 'Collapse Food' }));
		expect(table.querySelectorAll('tbody tr')).toHaveLength(2);
	});

	it('has the tree with a column per period and a total, each cell a link', async () => {
		const { container } = render(OverTimeView, {
			props: { report: overTimeCategories(), categories, scope }
		});

		const table = container.querySelector('[data-slot="category-trend-table"]') as HTMLElement;
		await fireEvent.click(screen.getByRole('button', { name: 'Expand Food' }));
		// the "(itself)" total is the server's own_sum
		expect(table.querySelector('[data-itself="true"] td:last-child')).toHaveTextContent('−50.00');
		const groceries = table.querySelector('[data-category="2"]') as HTMLElement;
		const links = [...groceries.querySelectorAll('a')].map((a) => a.getAttribute('href'));
		expect(links).toEqual([
			'/ledger?from=2026-08-01&to=2026-08-31&category_id=2',
			'/ledger?from=2026-09-01&to=2026-09-30&category_id=2',
			'/ledger?from=2026-10-01&to=2026-10-31&category_id=2'
		]);
		expect(table.querySelector('[data-itself="true"]')).toHaveTextContent('Food (itself)');
		expect(table.querySelector('[data-row="total"]')).toHaveTextContent('−915.00');
		// the total is read by its measure, the kind's
		expectStone(tileOf(table.querySelector('[data-row="total"] th'), 'receipt'));
	});

	it('draws the stack chart at a fixed height', () => {
		const { container } = render(OverTimeView, {
			props: { report: overTimeCategories(), categories, scope }
		});

		const chart = container.querySelector(
			'[data-slot="category-stack-chart"] [data-slot="chart"]'
		)!;
		expect(chart).toHaveClass('h-72', 'aspect-auto');
	});
});

describe('BalancesView', () => {
	it('opens collapsed to net worth and the kinds, each kind with its own net worth', async () => {
		const { container } = render(BalancesView, { props: { report: balances(), accounts } });

		const table = container.querySelector('[data-slot="balances-table"]') as HTMLElement;
		expect(
			[...table.querySelectorAll('tbody tr')].map(
				(tr) => tr.getAttribute('data-row') ?? tr.getAttribute('data-group')
			)
		).toEqual(['net-worth', 'checking', 'savings', 'depot']);
		// the kind's figures are the server's; the depot has none valued
		expect(table.querySelector('[data-group="checking"]')).toHaveTextContent('Checking');
		expect(table.querySelector('[data-group="checking"]')).toHaveTextContent('1,000.00');
		expect(table.querySelector('[data-group="savings"]')).toHaveTextContent('4,000.00');
		expect(
			table.querySelector('[data-group="depot"] [data-slot="absent-value"]')
		).toHaveTextContent('unvalued');
		// no toggle for a kind with no account beneath it
		expect(screen.queryByRole('button', { name: /Depot/ })).toBeNull();

		const toggle = screen.getByRole('button', { name: 'Expand Checking' });
		expect(toggle).toHaveAttribute('aria-expanded', 'false');
		await fireEvent.click(toggle);
		expect(
			[...table.querySelectorAll('tbody tr')].map(
				(tr) => tr.getAttribute('data-row') ?? tr.getAttribute('data-group')
			)
		).toEqual(['net-worth', 'checking', 'a1', 'savings', 'depot']);
		await fireEvent.click(screen.getByRole('button', { name: 'Collapse Checking' }));
		expect(table.querySelector('[data-row="a1"]')).toBeNull();
	});

	it('has net worth and the accounts grouped by kind against the month-ends', async () => {
		const { container } = render(BalancesView, { props: { report: balances(), accounts } });
		await fireEvent.click(screen.getByRole('button', { name: 'Expand Checking' }));

		const table = container.querySelector('[data-slot="balances-table"]') as HTMLElement;
		expect([...table.querySelectorAll('thead th')].map((th) => th.textContent?.trim())).toEqual([
			'EUR',
			'Aug 26',
			'Sep 26',
			'Oct 20, 2026'
		]);
		expect(table.querySelector('[data-row="net-worth"]')).toHaveTextContent('5,000.00');
		expect(table.querySelector('[data-group="checking"]')).toBeInTheDocument();
		expect(table.querySelector('[data-row="a1"] a')).toHaveAttribute('href', '/accounts/1');
	});

	it('leads net worth with sigma, a kind with its stone tile, an account with its own', async () => {
		const { container } = render(BalancesView, { props: { report: balances(), accounts } });
		await fireEvent.click(screen.getByRole('button', { name: 'Expand Checking' }));
		const table = container.querySelector('[data-slot="balances-table"]') as HTMLElement;

		expectStone(tileOf(table.querySelector('[data-row="net-worth"] th'), 'sigma'));
		expectStone(tileOf(table.querySelector('[data-group="checking"] th'), 'landmark'));
		expectStone(tileOf(table.querySelector('[data-group="savings"] th'), 'piggy-bank'));
		// Giro: a checking account in forest, so its tile carries the kind's glyph in its own colour
		const giro = tileOf(table.querySelector('[data-row="a1"] th'), 'landmark');
		expect(giro).not.toBeNull();
		expect(giro!.style.getPropertyValue('--tile-fg')).toBe(dimensionVars('forest').fg);
	});

	it('draws the same marks in the chart toggles and beside the unvalued accounts', () => {
		const { container } = render(BalancesView, { props: { report: balances(), accounts } });
		const toggles = container.querySelector('[data-slot="account-toggles"]');

		expectStone(tileOf(toggles!.querySelector('label:has([type=checkbox])'), 'sigma'));
		// the kind group label (the second, after "Total") is its stone tile
		expectStone(tileOf(toggles!.querySelectorAll('span.w-28')[1], 'landmark'));
		const giro = tileOf(
			screen.getByRole('checkbox', { name: 'Giro' }).closest('label'),
			'landmark'
		);
		expect(giro!.style.getPropertyValue('--tile-fg')).toBe(dimensionVars('forest').fg);
		const depot = tileOf(container.querySelector('[data-slot="unvalued"] li'), 'chart-line');
		expect(depot!.style.getPropertyValue('--tile-fg')).toBe(dimensionVars('plum').fg);
	});

	it('lists an account with no valued balance beneath, not in the table', () => {
		const { container } = render(BalancesView, { props: { report: balances(), accounts } });

		expect(container.querySelector('[data-row="a3"]')).toBeNull();
		const unvalued = container.querySelector('[data-slot="unvalued"]') as HTMLElement;
		expect(unvalued).toHaveTextContent('Not in the chart');
		expect(unvalued).toHaveTextContent('Depot');
		expect(unvalued).toHaveTextContent('80.00 USD');
	});

	it('shows no balance yet as a plain muted dash, and keeps "unvalued" as an absent value', async () => {
		const base = balances();
		const report = balances({
			accounts: [
				{
					...base.accounts[0],
					balances: [null, ...base.accounts[0].balances.slice(1)],
					native: [{ amount: 0, currency: 'EUR' }, ...base.accounts[0].native.slice(1)]
				},
				{
					...base.accounts[1],
					balances: [null, ...base.accounts[1].balances.slice(1)],
					native: [{ amount: 5000, currency: 'USD' }, ...base.accounts[1].native.slice(1)]
				}
			]
		});
		const { container } = render(BalancesView, { props: { report, accounts } });
		await fireEvent.click(screen.getByRole('button', { name: 'Expand Checking' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Expand Savings' }));

		const empty = container.querySelector('[data-row="a1"] td') as HTMLElement;
		expect(empty).toHaveTextContent('no balance yet');
		expect(empty.querySelector('[data-slot="absent-value"]')).toBeNull();
		expect(empty.querySelector('.text-muted-foreground')).toHaveTextContent('—');
		const unvalued = container.querySelector('[data-row="a2"] td') as HTMLElement;
		expect(unvalued.querySelector('[data-slot="absent-value"]')).toHaveTextContent('unvalued');
	});

	it('toggles an account into the chart by checkbox', async () => {
		render(BalancesView, { props: { report: balances(), accounts } });
		const toggle = screen.getByRole('checkbox', { name: 'Giro' });
		expect(toggle).not.toBeChecked();

		await fireEvent.click(toggle);

		expect(toggle).toBeChecked();
	});

	it('toggles the net worth out of the chart, and says so when nothing is left', async () => {
		const { container } = render(BalancesView, { props: { report: balances(), accounts } });
		const net = screen.getByRole('checkbox', { name: 'Net worth' });
		expect(net).toBeChecked();
		expect(container.querySelector('[data-slot="balance-chart"]')).not.toBeNull();

		await fireEvent.click(net);

		expect(net).not.toBeChecked();
		expect(container.querySelector('[data-slot="balance-chart"]')).toBeNull();
		expect(container.querySelector('[data-slot="nothing-selected"]')).toHaveTextContent(
			'Nothing selected.'
		);
		// the table stays as it is
		expect(container.querySelector('[data-row="net-worth"]')).toHaveTextContent('5,000.00');

		await fireEvent.click(screen.getByRole('checkbox', { name: 'Giro' }));
		expect(container.querySelector('[data-slot="balance-chart"]')).not.toBeNull();
	});
});
