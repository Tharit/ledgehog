import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { line } from '#lib/reports/fixtures.js';
import type { Scope } from '#lib/reports/links.js';
import { byAccount, byAccountLookups } from '#lib/reports/trend-fixtures.js';
import ByAccountView from './by-account-view.svelte';

const { categories, accounts } = byAccountLookups();
const scope: Scope = { from: '2026-10-01', to: '2026-10-31', accountIds: [], tagIds: [] };

const rowsOf = (container: Element, section: string) =>
	[...container.querySelectorAll(`[data-section="${section}"] tr[data-row]`)].map((tr) =>
		tr.getAttribute('data-row')
	);

describe('ByAccountView', () => {
	it('opens the table collapsed to its top level, and a group row expands its accounts', async () => {
		const { container } = render(ByAccountView, {
			props: { report: byAccount(), categories, accounts, scope }
		});

		expect(rowsOf(container, 'income')).toEqual(['income:c5', 'income:c7', 'income:total']);
		await fireEvent.click(screen.getByRole('button', { name: 'Expand Salary' }));
		expect(rowsOf(container, 'income').slice(0, 3)).toEqual([
			'income:c5',
			'income:c5:a1',
			'income:c7'
		]);
		await fireEvent.click(screen.getByRole('button', { name: 'Collapse Salary' }));
		expect(rowsOf(container, 'income')).toHaveLength(3);

		// the transfers: the sending accounts, their receivers folded away
		expect(rowsOf(container, 'transfers')).toEqual([
			'transfers:a1',
			'transfers:a2',
			'transfers:a3'
		]);
		// not in the categories above: unclassified out and in, reconciliations
		expect(rowsOf(container, 'other')).toEqual([
			'other:unclassified-out',
			'other:unclassified-in',
			'other:reconciliations'
		]);
	});

	it('links every figure of the table to the ledger, a group without a figure to nothing', async () => {
		const { container } = render(ByAccountView, {
			props: { report: byAccount(), categories, accounts, scope }
		});
		const row = (key: string) => container.querySelector(`tr[data-row="${key}"]`)!;

		expect(row('income:c5').querySelector('a')).toHaveAttribute(
			'href',
			'/ledger?from=2026-10-01&to=2026-10-31&category_id=5'
		);
		// a line beside the tree: its total, linked as By category links it
		expect(row('other:unclassified-out').querySelector('a')).toHaveAttribute(
			'href',
			'/ledger?from=2026-10-01&to=2026-10-31&uncategorised=true&direction=out'
		);
		// a sending account's total is a figure, not a link: no filter lists exactly its legs
		expect(row('transfers:a1').querySelector('a')).toBeNull();
		expect(row('transfers:a1').querySelector('[data-slot="figure"]')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Expand Giro' }));
		const leg = row('transfers:a1:a2').querySelector('a')!;
		expect(leg.getAttribute('href')).toContain('counter_account_id=2');
		expect(leg.getAttribute('href')).toContain('type=transfer');
	});

	it('names the links of the other sign in a note, with their figures as links', () => {
		render(ByAccountView, { props: { report: byAccount(), categories, accounts, scope } });

		const note = screen
			.getByText(/Not in the chart, since their net is of the other sign/)
			.closest('p')!;
		expect(note).toHaveTextContent('Giro to Refunds');
		expect(note).toHaveTextContent('Depot to Savings');
		expect(note.querySelectorAll('a')).toHaveLength(3);
	});

	it('counts the transfers not paired yet, with their figure as a link to the ledger’s unpaired legs', () => {
		const { container } = render(ByAccountView, {
			props: { report: byAccount(), categories, accounts, scope: { ...scope, tagIds: [4] } }
		});

		const note = container.querySelector('[data-slot="unpaired-note"]')!;
		expect(note).toHaveTextContent(/^\s*Not paired yet: 2 transfers/);
		expect(note).not.toHaveTextContent(/Not in the chart/);
		const href = note.querySelector('a')!.getAttribute('href')!;
		const query = new URLSearchParams(href.split('?')[1]);
		expect(href.startsWith('/ledger?')).toBe(true);
		expect(query.getAll('type')).toEqual(['transfer']);
		expect(query.getAll('flag')).toEqual(['waiting', 'unmatched_transfer']);
		expect(query.getAll('tag_id')).toEqual(['4']);
		expect(query.get('from')).toBe('2026-10-01');
	});

	it('has no unpaired note at a count of 0', () => {
		const { container } = render(ByAccountView, {
			props: { report: byAccount({ unpaired: line(0) }), categories, accounts, scope }
		});
		expect(container.querySelector('[data-slot="unpaired-note"]')).toBeNull();
	});

	it('says nothing is there, with the filters when there are some', () => {
		const empty = byAccount({
			income: { total: line(0), categories: [], slices: [], other: [] },
			expense: { total: line(0), categories: [], slices: [], other: [] },
			unclassified_in: { total: line(0), accounts: [] },
			unclassified_out: { total: line(0), accounts: [] },
			reconciliations: { total: line(0), accounts: [] },
			transfers: [],
			unpaired: line(0),
			stayed: []
		});
		const plain = render(ByAccountView, {
			props: { report: empty, categories, accounts, scope }
		});
		expect(plain.container.querySelector('[data-slot="nothing"]')).toHaveTextContent(
			'Nothing in this period.'
		);
		plain.unmount();

		const tagged = render(ByAccountView, {
			props: { report: empty, categories, accounts, scope: { ...scope, tagIds: [4] } }
		});
		expect(tagged.container.querySelector('[data-slot="nothing"]')).toHaveTextContent(
			'Nothing in this period with these filters.'
		);
	});
});
