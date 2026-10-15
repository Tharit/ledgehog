import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { account, category, entry, payee, tag } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { COLUMNS, GRID_TEMPLATE } from './columns.js';
import EntryRow from './entry-row.svelte';

const lookups = buildLookups({
	accounts: [
		account(),
		account({ id: 2, name: 'Cash', kind: 'cash', color: 'ochre' }),
		account({ id: 3, name: 'Visa', kind: 'card', color: null })
	],
	categories: [category()],
	payees: [payee()],
	tags: [
		tag(),
		tag({ id: 31, name: 'Tax', color: null }),
		tag({ id: 32, name: 'Gift', color: 'plum' })
	]
});

/** the index of a column's cell in a row */
function cell(id: string): number {
	return COLUMNS.findIndex((c) => c.id === id);
}

function row(over = {}, props = {}) {
	return render(EntryRow, { props: { entry: entry(over), lookups, ...props } });
}

describe('EntryRow: a flow entry', () => {
	it('shows date, account, text, payee, category and amount', () => {
		row({ description: 'REWE Markt', payee_id: 20, category_id: 10 });

		const cells = within(screen.getByRole('row')).getAllByRole('gridcell');
		expect(cells[0]).toHaveTextContent('Oct 9, 2026');
		expect(cells).toHaveLength(COLUMNS.length);
		expect(cells[cell('account')]).toHaveTextContent('Giro');
		expect(cells[cell('description')]).toHaveTextContent('REWE Markt');
		expect(cells[cell('payee')]).toHaveTextContent('REWE');
		expect(cells[cell('category')]).toHaveTextContent('Groceries');
		expect(cells.at(-1)).toHaveTextContent('−47.31');
	});

	it('is a 32px row', () => {
		row();

		expect(screen.getByRole('row')).toHaveClass('h-8');
	});

	it('follows the column definition: one cell per column, in its order', () => {
		row({ payee_id: 20, category_id: 10 });

		expect(COLUMNS.map((c) => c.id)).toEqual([
			'date',
			'account',
			'category',
			'payee',
			'tags',
			'description',
			'review',
			'amount'
		]);
		expect(screen.getByRole('row').style.gridTemplateColumns).toBe(GRID_TEMPLATE);
	});

	it('gives the description its full text as a tooltip', () => {
		row({ description: 'A long purpose text' });

		expect(screen.getByTitle('A long purpose text')).toBeInTheDocument();
	});

	it("shows the entry's own description only: nothing borrowed from the source", () => {
		row({ description: null, display_text: 'REWE Markt' });

		expect(screen.queryByText('REWE Markt')).toBeNull();
	});

	it('leaves the cell empty, without a placeholder, when the description is empty', () => {
		row({ description: null });

		const cells = within(screen.getByRole('row')).getAllByRole('gridcell');
		expect(cells[cell('description')]).toBeEmptyDOMElement();
		expect(screen.queryByText('No text')).toBeNull();
	});

	it('shows Unclassified as an absent value, with the badge the server sent', () => {
		row({ category_id: null, review_flags: ['unclassified', 'unconfirmed'] });

		expect(screen.getByText('Unclassified')).toHaveClass('decoration-dotted');
		expect(screen.getByTitle('Type or category missing')).toBeInTheDocument();
		expect(screen.getByTitle('Values are proposals')).toBeInTheDocument();
	});

	it('shows no badge for a confirmed entry', () => {
		row({ category_id: 10 });

		expect(screen.queryByRole('img')).toBeNull();
	});

	it('falls back to a generic name for a category it does not know', () => {
		row({ category_id: 99 });

		expect(screen.getByText('Category 99')).toBeInTheDocument();
	});

	it('writes the currency only when asked to', () => {
		const { container } = row({}, { showCurrency: true });

		expect(container.textContent).toContain('−47.31 EUR');
	});
});

describe('EntryRow: tags', () => {
	it('shows up to two chips', () => {
		row({ tag_ids: [30, 31] });

		expect(screen.getByText('Lisbon trip')).toBeInTheDocument();
		expect(screen.getByText('Tax')).toBeInTheDocument();
		expect(screen.queryByText(/^\+\d/)).toBeNull();
	});

	it('shows "+N" for the rest, naming them in a tooltip', () => {
		row({ tag_ids: [30, 31, 32] });

		expect(screen.getByText('Lisbon trip')).toBeInTheDocument();
		expect(screen.queryByText('Gift')).toBeNull();
		expect(screen.getByText('+1')).toHaveAttribute('title', 'Gift');
	});

	it('reports a click on the tags cell, the mouse path of the t key', async () => {
		const ontags = vi.fn();
		row({ tag_ids: [] }, { ontags });

		await fireEvent.click(screen.getByRole('button', { name: 'Edit tags' }));

		expect(ontags).toHaveBeenCalledOnce();
	});

	it('skips a tag it has no name for', () => {
		row({ tag_ids: [999] });

		expect(screen.queryByText(/^\+\d/)).toBeNull();
	});
});

describe('EntryRow: transfers', () => {
	it('shows the arrow icon and the counter account', () => {
		row({ type: 'transfer', counter_account_id: 2, category_id: null });

		const categoryCell = within(screen.getByRole('row')).getAllByRole('gridcell')[cell('category')];
		expect(categoryCell).toHaveTextContent('→');
		expect(categoryCell).toHaveTextContent('Cash');
		expect(screen.queryByText('Unclassified')).toBeNull();
	});

	it('shows an absent counter account as "→ ?"', () => {
		row({ type: 'transfer', counter_account_id: null });

		expect(screen.getByText('→ ?')).toHaveAttribute('title', expect.stringContaining('counter'));
	});
});

describe('EntryRow: derived entries', () => {
	it.each([
		['opening', 'Opening'],
		['valuation', 'Valuation'],
		['reconciliation', 'Reconciliation']
	] as const)('%s shows its type in place of a category, no payee, no badges', (type, name) => {
		row({
			type,
			description: null,
			payee_id: 20,
			review_flags: ['unconfirmed']
		});

		const cells = within(screen.getByRole('row')).getAllByRole('gridcell');
		expect(cells[cell('category')]).toHaveTextContent(name);
		expect(cells[cell('payee')]).toBeEmptyDOMElement();
		expect(screen.queryByRole('img')).toBeNull();
		expect(screen.queryByText('No text')).toBeNull();
	});
});

describe('EntryRow: the cursor', () => {
	it('has the accent background and a bar on its left edge', () => {
		row({}, { cursor: true });

		const element = screen.getByRole('row');
		expect(element).toHaveAttribute('aria-selected', 'true');
		expect(element).toHaveClass('bg-accent');
		expect(element.querySelector('.bg-primary.w-0\\.5')).not.toBeNull();
	});

	it('is plain without the cursor', () => {
		row();

		expect(screen.getByRole('row')).toHaveAttribute('aria-selected', 'false');
		expect(screen.getByRole('row')).not.toHaveClass('bg-accent');
	});

	it('reports a click', async () => {
		const onselect = vi.fn();
		row({}, { onselect });

		await fireEvent.click(screen.getByRole('row'));

		expect(onselect).toHaveBeenCalledOnce();
	});
});
