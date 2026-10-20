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
import BalancesView from './balances-view.svelte';
import ByCategoryView from './by-category-view.svelte';
import OverTimeView from './over-time-view.svelte';

const { categories, accounts } = reportLookups();
const scope: Scope = { from: '2026-10-01', to: '2026-10-31', accountIds: [], tagIds: [] };

function hrefOf(row: HTMLElement): string | null {
	return row.querySelector('a')?.getAttribute('href') ?? null;
}

describe('ByCategoryView', () => {
	it('lists the category tree with every amount linking to the ledger', () => {
		render(ByCategoryView, { props: { report: byCategoryTree(), categories, scope } });

		const table = screen.getByRole('table');
		const food = within(table).getByRole('row', { name: /^Food\b(?! \(itself\))/ });
		expect(hrefOf(food)).toBe('/ledger?from=2026-10-01&to=2026-10-31&category_id=1');
		const itself = within(table).getByRole('row', { name: /Food \(itself\)/ });
		expect(hrefOf(itself)).toBe(
			'/ledger?from=2026-10-01&to=2026-10-31&category_id=1&category_descendants=false'
		);
		expect(within(table).getByRole('row', { name: /Home/ })).toBeInTheDocument();
	});

	it('names the category of the other sign in a note rather than drawing it', () => {
		render(ByCategoryView, { props: { report: byCategoryTree(), categories, scope } });

		const note = screen.getByText(/Not in the chart/).closest('p')!;
		expect(note).toHaveTextContent('Refunds');
		expect(screen.queryByText('Refunds', { selector: '[data-slice] *' })).toBeNull();
	});

	it('writes the legend with "Other" and no link for it', () => {
		const { container } = render(ByCategoryView, {
			props: { report: byCategoryTree(), categories, scope }
		});

		const other = container.querySelector('[data-slice="other"]')!;
		expect(other).toHaveTextContent('Other');
		expect(other.querySelector('a')).toBeNull();
		expect(container.querySelector('[data-slice="c4"] a')).toHaveAttribute(
			'href',
			'/ledger?from=2026-10-01&to=2026-10-31&category_id=4'
		);
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
		expect(side.querySelector('[data-line="unconfirmed"]')).toHaveTextContent('3 entries');
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
});

describe('OverTimeView, by category', () => {
	it('has the tree with a column per period and a total, each cell a link', () => {
		const { container } = render(OverTimeView, {
			props: { report: overTimeCategories(), categories, scope }
		});

		const table = container.querySelector('[data-slot="category-trend-table"]') as HTMLElement;
		const groceries = table.querySelector('[data-category="2"]') as HTMLElement;
		const links = [...groceries.querySelectorAll('a')].map((a) => a.getAttribute('href'));
		expect(links).toEqual([
			'/ledger?from=2026-08-01&to=2026-08-31&category_id=2',
			'/ledger?from=2026-09-01&to=2026-09-30&category_id=2',
			'/ledger?from=2026-10-01&to=2026-10-31&category_id=2'
		]);
		expect(table.querySelector('[data-itself="true"]')).toHaveTextContent('Food (itself)');
		expect(table.querySelector('[data-row="total"]')).toHaveTextContent('−915.00');
	});
});

describe('BalancesView', () => {
	it('has net worth and the accounts grouped by kind against the month-ends', () => {
		const { container } = render(BalancesView, { props: { report: balances(), accounts } });

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

	it('lists an account with no valued balance beneath, not in the table', () => {
		const { container } = render(BalancesView, { props: { report: balances(), accounts } });

		expect(container.querySelector('[data-row="a3"]')).toBeNull();
		const unvalued = container.querySelector('[data-slot="unvalued"]') as HTMLElement;
		expect(unvalued).toHaveTextContent('Not in the chart');
		expect(unvalued).toHaveTextContent('Depot');
		expect(unvalued).toHaveTextContent('80.00 USD');
	});

	it('toggles an account into the chart by checkbox', async () => {
		render(BalancesView, { props: { report: balances(), accounts } });
		const toggle = screen.getByRole('checkbox', { name: 'Giro' });
		expect(toggle).not.toBeChecked();

		await fireEvent.click(toggle);

		expect(toggle).toBeChecked();
	});
});
