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
			'origin',
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
		expect(cells[cell('description')].textContent?.trim()).toBe('');
		expect(screen.queryByText('No text')).toBeNull();
	});

	it.each([
		['import', 'Imported'],
		['user', 'Entered'],
		['booking', 'Booked']
	] as const)('tags a row of origin %s as %s, muted', (origin, word) => {
		row({ origin });

		const cells = within(screen.getByRole('row')).getAllByRole('gridcell');
		expect(cells[cell('origin')]).toHaveTextContent(word);
		expect(screen.getByText(word)).toHaveClass('text-muted-foreground');
	});

	it('has no origin tag on a derived entry', () => {
		row({ type: 'opening', origin: null });

		const cells = within(screen.getByRole('row')).getAllByRole('gridcell');
		expect(cells[cell('origin')].textContent?.trim()).toBe('');
	});

	it('shows the source text muted, then the description the user gave', () => {
		row({ source_text: 'USB cable', description: 'for the office' });

		const text = within(screen.getByRole('row')).getAllByRole('gridcell')[cell('description')];
		expect(text.textContent?.replace(/\s+/g, ' ').trim()).toBe('USB cable for the office');
		expect(screen.getByText('USB cable')).toHaveClass('text-muted-foreground');
		expect(screen.getByText('for the office')).not.toHaveClass('text-muted-foreground');
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

describe('EntryRow: the partner summary', () => {
	const partner = {
		entry_id: 9,
		account_id: 2,
		booked_on: '2026-10-08',
		amount: { amount: 10000, currency: 'EUR' }
	};

	it('gives a paired leg its partner (account, date, amount) as a tooltip on the cell', () => {
		row({ type: 'transfer', counter_account_id: 2, counterpart_entry_id: 9, partner });

		const categoryCell = within(screen.getByRole('row')).getAllByRole('gridcell')[cell('category')];
		expect(categoryCell.getAttribute('title')).toMatch(/^↔ Cash · Oct 8, 2026 · \+100\.00\s+EUR$/);
	});

	it('names an account it does not know by its id', () => {
		row({
			type: 'transfer',
			counter_account_id: 2,
			counterpart_entry_id: 9,
			partner: { ...partner, account_id: 77 }
		});

		const categoryCell = within(screen.getByRole('row')).getAllByRole('gridcell')[cell('category')];
		expect(categoryCell.getAttribute('title')).toContain('↔ Account 77');
	});

	it('gives an unpaired leg no summary and keeps "→ ?"', () => {
		row({ type: 'transfer', counter_account_id: null, partner: null });

		const categoryCell = within(screen.getByRole('row')).getAllByRole('gridcell')[cell('category')];
		expect(categoryCell).not.toHaveAttribute('title');
		expect(screen.getByText('→ ?')).toBeInTheDocument();
	});

	it('gives a flow no summary', () => {
		row({ type: 'flow', partner });

		const categoryCell = within(screen.getByRole('row')).getAllByRole('gridcell')[cell('category')];
		expect(categoryCell).not.toHaveAttribute('title');
	});

	it('words the clock on a transfer leg without a partner as a missing partner', () => {
		row({ type: 'transfer', review_flags: ['waiting'] });

		expect(screen.getByTitle('Its partner has probably not been imported yet')).toHaveAttribute(
			'data-flag',
			'waiting'
		);
	});

	it('keeps the general words of the clock on a flow', () => {
		row({ type: 'flow', review_flags: ['waiting'] });

		expect(screen.getByTitle('Partner still expected')).toBeInTheDocument();
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

describe('EntryRow: overflow', () => {
	const longAccounts = buildLookups({
		accounts: [
			account({ id: 1, name: 'A checking account with a very long name indeed' }),
			account({ id: 2, name: 'Another account with an equally long name', color: 'ochre' })
		],
		categories: [category()],
		payees: [payee({ id: 20, name: 'A payee whose name does not fit in its column at all' })]
	});

	it('clips every cell, so no content spills into a neighbour', () => {
		row({ payee_id: 20, category_id: 10 });

		for (const gridcell of within(screen.getByRole('row')).getAllByRole('gridcell')) {
			expect(gridcell).toHaveClass('min-w-0');
		}
	});

	it('truncates a long account name and shows it whole as a tooltip', () => {
		render(EntryRow, { props: { entry: entry({}), lookups: longAccounts } });

		const accountCell = screen.getAllByRole('gridcell')[cell('account')];
		expect(accountCell).toHaveAttribute('title', 'A checking account with a very long name indeed');
		expect(accountCell.querySelector('[data-slot="account-dot"]')?.parentElement).toHaveClass(
			'max-w-full',
			'min-w-0'
		);
		expect(accountCell.querySelector('.truncate')).toHaveTextContent('A checking account');
	});

	it('titles a long payee and a long category name', () => {
		render(EntryRow, {
			props: { entry: entry({ payee_id: 20, category_id: 10 }), lookups: longAccounts }
		});

		const cells = screen.getAllByRole('gridcell');
		expect(cells[cell('payee')]).toHaveAttribute(
			'title',
			'A payee whose name does not fit in its column at all'
		);
		expect(cells[cell('payee')]).toHaveClass('truncate');
		expect(cells[cell('category')].querySelector('.truncate')).toHaveAttribute('title');
	});
});
