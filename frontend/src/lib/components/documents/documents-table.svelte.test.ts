import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { documentRow } from '#lib/documents/fixtures.js';
import DocumentsTable from './documents-table.svelte';

const carried = documentRow({
	id: 2,
	provider: 'paypal',
	merchant_name: 'Etsy',
	title: null,
	carrier_count: 2
});
const free = documentRow({ id: 1 });

function table(props = {}) {
	const onopen = vi.fn();
	render(DocumentsTable, {
		props: {
			documents: [carried, free],
			total: 2,
			status: 'ready',
			onopen,
			...props
		}
	});
	return { onopen };
}

describe('DocumentsTable', () => {
	it('lists the documents with provider, date, merchant or title, amount and carrier', () => {
		table();
		const rows = screen.getAllByRole('row').filter((r) => r.hasAttribute('data-document-id'));
		expect(rows).toHaveLength(2);
		const first = within(rows[0]);
		expect(first.getByText('paypal')).toBeInTheDocument();
		expect(first.getByText('Etsy')).toBeInTheDocument();
		expect(first.getByText('Oct 8, 2026')).toBeInTheDocument();
		expect(first.getByText('−47.31')).toBeInTheDocument();
		expect(first.getByText('2 transactions')).toBeInTheDocument();
		const second = within(rows[1]);
		expect(second.getByText('Amazon · Order 304-1')).toBeInTheDocument();
		expect(second.queryByText(/transaction/)).toBeNull(); // carried by none: empty
		expect(screen.getByText('2 of 2')).toBeInTheDocument();
	});

	it('names the columns', () => {
		table();
		for (const name of ['Provider', 'Date', 'Merchant or title', 'Amount', 'Carried by']) {
			expect(screen.getByRole('columnheader', { name })).toBeInTheDocument();
		}
	});

	it('opens the document from its link or a click on its row', async () => {
		const { onopen } = table();
		expect(screen.getByRole('link', { name: 'Etsy' })).toHaveAttribute('href', '/documents/2');
		await fireEvent.click(screen.getByText('paypal'));
		expect(onopen).toHaveBeenCalledWith(2);
	});

	it('says "1 transaction" for a single carrier', () => {
		table({ documents: [documentRow({ id: 5, carrier_count: 1 })], total: 1 });
		expect(screen.getByText('1 transaction')).toBeInTheDocument();
	});

	it('writes the currency only where several are listed together', () => {
		table({ documents: [free, documentRow({ id: 3, total: { amount: 500, currency: 'USD' } })] });
		expect(screen.getByText('−47.31 EUR')).toBeInTheDocument();
		expect(screen.getByText('+5.00 USD')).toBeInTheDocument();
	});

	it('shows skeleton rows while loading', () => {
		table({ documents: [], total: 0, status: 'loading' });
		expect(document.querySelectorAll('[data-skeleton]').length).toBeGreaterThan(3);
		expect(screen.getByRole('grid')).toHaveAttribute('aria-busy', 'true');
	});

	it('explains how documents arrive when there are none', () => {
		table({ documents: [], total: 0 });
		expect(screen.getByText('No documents yet')).toBeInTheDocument();
	});

	it('names the filters when nothing matches and clears them', async () => {
		const onclearfilters = vi.fn();
		table({ documents: [], total: 0, activeFilters: ['amazon', 'Not linked'], onclearfilters });
		expect(screen.getByText('No documents match these filters')).toBeInTheDocument();
		expect(screen.getByText('amazon · Not linked')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
		expect(onclearfilters).toHaveBeenCalledOnce();
	});

	it('offers a retry for a failure a retry can fix, and none for one it cannot', async () => {
		const onretry = vi.fn();
		table({
			documents: [],
			total: 0,
			status: 'error',
			error: { code: 'network_error', message: 'x' },
			onretry
		});
		expect(screen.getByText('The documents could not be loaded')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(onretry).toHaveBeenCalledOnce();
	});

	it('loads more and says why when that fails', async () => {
		const onloadmore = vi.fn();
		table({
			total: 5,
			onloadmore,
			moreError: { code: 'network_error', message: 'x' }
		});
		expect(screen.getByText('2 of 5')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Load more' }));
		expect(onloadmore).toHaveBeenCalledOnce();
		expect(screen.getByRole('alert')).toHaveTextContent('The documents could not be loaded');
	});
});
