import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { documentRow } from '#lib/documents/fixtures.js';
import { account } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import DocumentsTable from './documents-table.svelte';

const lookups = buildLookups({ accounts: [account()] });
const carried = documentRow({
	id: 2,
	provider: 'paypal',
	merchant_name: 'Etsy',
	title: null,
	carrier: {
		entry_id: 40,
		source_transaction_id: 400,
		account_id: 1,
		booked_on: '2026-10-09',
		amount: { amount: -4731, currency: 'EUR' }
	}
});
const free = documentRow({ id: 1 });

function table(props = {}) {
	const onopen = vi.fn();
	const onopencarrier = vi.fn();
	render(DocumentsTable, {
		props: {
			documents: [carried, free],
			total: 2,
			status: 'ready',
			lookups,
			onopen,
			onopencarrier,
			...props
		}
	});
	return { onopen, onopencarrier };
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
		expect(first.getByRole('button', { name: /Giro/ })).toBeInTheDocument();
		const second = within(rows[1]);
		expect(second.getByText('Amazon · Order 304-1')).toBeInTheDocument();
		expect(second.getByText('Not linked')).toBeInTheDocument();
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

	it('opens the carrying transaction, and only that', async () => {
		const { onopen, onopencarrier } = table();
		await fireEvent.click(screen.getByRole('button', { name: /Giro/ }));
		expect(onopencarrier).toHaveBeenCalledWith(40, expect.any(HTMLElement));
		expect(onopen).not.toHaveBeenCalled();
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
