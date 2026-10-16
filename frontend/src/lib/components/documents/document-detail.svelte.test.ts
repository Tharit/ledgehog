import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { documentDetail, documentMatch } from '#lib/documents/fixtures.js';
import { account, payee } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import type { DocumentDetail } from '#lib/types/domain.js';
import DocumentDetailView from './document-detail.svelte';

const lookups = buildLookups({
	accounts: [account(), account({ id: 2, name: 'Cash' })],
	payees: [payee({ id: 20, name: 'Amazon' })]
});

function view(document: DocumentDetail) {
	const onopencarrier = vi.fn();
	const onpickmatch = vi.fn();
	render(DocumentDetailView, { props: { document, lookups, onopencarrier, onpickmatch } });
	return { onopencarrier, onpickmatch };
}

describe('DocumentDetail', () => {
	it('shows the merchant, provider, date, total and the lines', () => {
		view(documentDetail());
		expect(
			screen.getByRole('heading', { level: 1, name: 'Amazon · Order 304-1' })
		).toBeInTheDocument();
		expect(screen.getByText('amazon · Oct 8, 2026')).toBeInTheDocument();
		expect(screen.getByText('−47.31 EUR')).toBeInTheDocument();
		const table = screen.getByRole('table');
		expect(within(table).getByText('USB cable')).toBeInTheDocument();
		expect(within(table).getByText('Book')).toBeInTheDocument();
		expect(within(table).getByText('−15.00')).toBeInTheDocument();
		expect(within(table).getByText('2')).toBeInTheDocument();
	});

	it('says when there are no lines', () => {
		view(documentDetail({ lines: [] }));
		expect(screen.getByText('This document has no lines.')).toBeInTheDocument();
		expect(screen.queryByRole('table')).toBeNull();
	});

	it('names the carrying transaction of a linked document, which opens the panel', async () => {
		const { onopencarrier } = view(
			documentDetail({
				carrier: {
					entry_id: 40,
					source_transaction_id: 400,
					account_id: 2,
					booked_on: '2026-10-09',
					amount: { amount: -4731, currency: 'EUR' }
				}
			})
		);
		await fireEvent.click(screen.getByRole('button', { name: /Cash/ }));
		expect(onopencarrier).toHaveBeenCalledWith(40, expect.any(HTMLElement));
		expect(screen.queryByText('Transactions it would match')).toBeNull();
	});

	it('lists the transactions an unlinked document would match, with their state', () => {
		view(
			documentDetail({
				matches: [
					documentMatch({ entry_id: 40, payee_id: 20, confirmed: false }),
					documentMatch({ entry_id: 41, display_text: 'AMZN', confirmed: true, document_id: 9 })
				]
			})
		);
		const list = screen.getByRole('list', { name: 'Matching transactions' });
		const items = within(list).getAllByRole('listitem');
		expect(items).toHaveLength(2);
		expect(within(items[0]).getByText('Amazon')).toBeInTheDocument();
		expect(within(items[0]).getByText('Unconfirmed')).toBeInTheDocument();
		expect(within(items[1]).getByText('AMZN')).toBeInTheDocument();
		expect(within(items[1]).getByText('Confirmed')).toBeInTheDocument();
		expect(within(items[1]).getByText('carries another document')).toBeInTheDocument();
	});

	it('opens the panel on a match with this document picked', async () => {
		const { onpickmatch } = view(
			documentDetail({ id: 7, matches: [documentMatch({ entry_id: 41 })] })
		);
		await fireEvent.click(screen.getByRole('button', { name: 'Open to review' }));
		expect(onpickmatch).toHaveBeenCalledWith(41, 7, expect.any(HTMLElement));
	});

	it('explains an unlinked document nothing would match', () => {
		view(documentDetail({ matches: [] }));
		expect(screen.getByText('No transaction would match this document')).toBeInTheDocument();
	});
});
