import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { recordRow, sourceRow } from '#lib/accounts/fixtures.js';
import { account } from '#lib/ledger/fixtures.js';
import StatementTable from './statement-table.svelte';

const eur = (amount: number) => ({ amount, currency: 'EUR' });

const items = [
	sourceRow({ id: 4, booked_on: '2026-10-12', counterparty_name: 'Netflix', amount: eur(-1299) }),
	recordRow({
		id: 2,
		balance_on: '2026-10-11',
		difference: eur(-350),
		balance: eur(90000),
		late_arrivals: 0
	}),
	sourceRow({
		id: 3,
		booked_on: '2026-10-10',
		counterparty_name: 'REWE',
		duplicate_of: { id: 2, booked_on: '2026-10-09', amount: eur(-4000) }
	}),
	sourceRow({
		id: 2,
		booked_on: '2026-10-09',
		authored: true,
		origin: 'user',
		counterparty_name: null
	}),
	recordRow({ id: 1, anchor: true, record_kind: 'manual', difference: eur(100000) })
];

function table(props = {}) {
	return render(StatementTable, {
		props: {
			items,
			total: items.length,
			status: 'ready',
			account: { kind: 'checking', records_since_zero: null },
			...props
		}
	});
}

const row = (key: string) => document.querySelector(`[data-item-key="${key}"]`) as HTMLElement;

describe('StatementTable headers', () => {
	it('names the account currency in the amount and balance headers, and the cells show none', () => {
		table({ account: { kind: 'checking', records_since_zero: null, currency: 'EUR' } });
		expect(screen.getByRole('columnheader', { name: 'Amount (EUR)' })).toBeInTheDocument();
		expect(screen.getByRole('columnheader', { name: 'Balance (EUR)' })).toBeInTheDocument();
		expect(within(row('source:4')).queryByText(/EUR/)).toBeNull();
	});

	it('falls back to the currency of the rows held', () => {
		table();
		expect(screen.getByRole('columnheader', { name: 'Amount (EUR)' })).toBeInTheDocument();
	});
});

describe('StatementTable rows', () => {
	it('shows a source row with its counterparty, purpose and amount, and an empty Balance cell', () => {
		table();
		const r = within(row('source:4'));
		expect(r.getByText('Netflix')).toBeInTheDocument();
		expect(r.getByText('−12.99')).toBeInTheDocument();
		const cells = r.getAllByRole('gridcell');
		expect(cells[cells.length - 1]).toBeEmptyDOMElement();
	});

	it('tags each row with its origin and shows nothing where an entered row has no counterparty', () => {
		table();
		expect(within(row('source:4')).getByText('Imported')).toBeInTheDocument();
		const entered = within(row('source:2'));
		expect(entered.queryByText('entered by hand')).toBeNull();
		expect(entered.queryByText('Imported')).toBeNull();
	});

	it('tags a booking and an entry by hand, whatever the account', () => {
		table({
			items: [
				sourceRow({ id: 8, origin: 'booking', counterparty_name: 'amazon', purpose: 'order 1' }),
				sourceRow({ id: 9, origin: 'user', counterparty_name: null, purpose: null })
			]
		});
		expect(within(row('source:8')).getByText('Booked')).toBeInTheDocument();
		expect(within(row('source:8')).getByText('amazon')).toBeInTheDocument();
		expect(within(row('source:9')).getByText('Entered')).toBeInTheDocument();
	});

	it('dims a duplicate and names the row it duplicates', () => {
		table();
		const dup = row('source:3');
		expect(dup).toHaveAttribute('data-duplicate');
		expect(
			within(dup).getByRole('button', { name: /duplicate of Oct 9, 2026 · −40\.00/ })
		).toBeInTheDocument();
	});

	it('opens the row a duplicate duplicates', async () => {
		const onopen = vi.fn();
		table({ onopen });
		await fireEvent.click(within(row('source:3')).getByRole('button', { name: /duplicate of/ }));
		expect(onopen).toHaveBeenCalledWith(2);
	});

	it('shows a record marker with the gap, and the anchor with its balance alone', () => {
		table();
		const marker = within(row('record:2'));
		expect(marker.getByText('Reported balance')).toBeInTheDocument();
		expect(marker.getByText('expected 903.50 · difference −3.50')).toBeInTheDocument();
		const anchor = within(row('record:1'));
		expect(anchor.getByText('Manual balance')).toBeInTheDocument();
		expect(anchor.getByText('opening 1,000.00')).toBeInTheDocument();
	});

	it('says how many bookings a reported record did not count, quietly', () => {
		table({
			items: [recordRow({ id: 9, late_arrivals: 1 }), recordRow({ id: 8, late_arrivals: 3 })]
		});
		expect(
			within(row('record:9')).getByText('1 booking dated before it arrived later')
		).toBeInTheDocument();
		expect(
			within(row('record:8')).getByText('3 bookings dated before it arrived later')
		).toBeInTheDocument();
	});

	it('calls the difference a valuation on an investment account', () => {
		table({ account: { kind: 'depot', records_since_zero: null } });
		expect(within(row('record:2')).getByText(/· valuation −3\.50/)).toBeInTheDocument();
	});

	it('marks the records that localise the unexplained difference', () => {
		table({ account: account({ kind: 'checking', records_since_zero: [2] }) });
		expect(within(row('record:2')).getByRole('img', { name: /Localises/ })).toBeInTheDocument();
		expect(
			within(row('record:1')).queryByRole('img', { name: /Localises/ })
		).not.toBeInTheDocument();
	});
});

describe('StatementTable keys and actions', () => {
	it('moves the cursor with the arrows and opens a source row with Enter or p', async () => {
		const onopen = vi.fn();
		table({ onopen });

		await fireEvent.keyDown(document.body, { key: 'ArrowDown' });
		expect(row('source:4')).toHaveAttribute('aria-selected', 'true');
		await fireEvent.keyDown(document.body, { key: 'Enter' });
		await fireEvent.keyDown(document.body, { key: 'p' });
		expect(onopen).toHaveBeenNthCalledWith(1, 4);
		expect(onopen).toHaveBeenNthCalledWith(2, 4);
	});

	it('opens no detail on a marker', async () => {
		const onopen = vi.fn();
		table({ onopen });
		await fireEvent.keyDown(document.body, { key: 'ArrowDown' });
		await fireEvent.keyDown(document.body, { key: 'ArrowDown' });
		expect(row('record:2')).toHaveAttribute('aria-selected', 'true');
		await fireEvent.keyDown(document.body, { key: 'Enter' });
		expect(onopen).not.toHaveBeenCalled();
	});

	it('opens a source row by click', async () => {
		const onopen = vi.fn();
		table({ onopen });
		await fireEvent.click(within(row('source:4')).getByText('Netflix'));
		expect(onopen).toHaveBeenCalledWith(4);
	});

	it('offers Edit on a manual record and Delete… on any record', async () => {
		const onedit = vi.fn();
		const ondelete = vi.fn();
		table({ onedit, ondelete });

		const manual = within(row('record:1'));
		await fireEvent.click(manual.getByRole('button', { name: /^Edit Manual balance/ }));
		await fireEvent.click(manual.getByRole('button', { name: /^Delete… Manual balance/ }));
		expect(onedit).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
		expect(ondelete).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));

		const reported = within(row('record:2'));
		expect(reported.queryByRole('button', { name: /^Edit/ })).not.toBeInTheDocument();
		expect(reported.getByRole('button', { name: /^Delete…/ })).toBeInTheDocument();
	});

	it('keeps the cursor on its row when the rows are replaced, and moves it to a neighbour when its row is gone', async () => {
		const { rerender } = table();
		await fireEvent.keyDown(document.body, { key: 'ArrowDown' });
		await fireEvent.keyDown(document.body, { key: 'ArrowDown' });
		await fireEvent.keyDown(document.body, { key: 'ArrowDown' });
		expect(row('source:3')).toHaveAttribute('aria-selected', 'true');

		await rerender({ items: [...items], total: items.length });
		expect(row('source:3')).toHaveAttribute('aria-selected', 'true');

		await rerender({ items: items.filter((i) => !(i.kind === 'source' && i.id === 3)), total: 4 });
		expect(document.querySelectorAll('[aria-selected="true"]')).toHaveLength(1);
		expect(row('source:2')).toHaveAttribute('aria-selected', 'true');
	});
});

describe('StatementTable states', () => {
	it('says how rows arrive when there are none', () => {
		table({ items: [], total: 0 });
		expect(screen.getByText('No rows yet')).toBeInTheDocument();
	});

	it('offers load more while rows are missing', async () => {
		const onloadmore = vi.fn();
		table({ total: 50, onloadmore });
		await fireEvent.click(screen.getByRole('button', { name: 'Load more' }));
		expect(onloadmore).toHaveBeenCalled();
		expect(screen.getByText('5 of 50')).toBeInTheDocument();
	});

	it('shows the error with Try again when the first page failed', async () => {
		const onretry = vi.fn();
		table({
			items: [],
			total: 0,
			status: 'error',
			error: { code: 'network_error', message: 'x' },
			onretry
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(onretry).toHaveBeenCalled();
	});
});
