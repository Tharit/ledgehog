import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { documentDetail } from '#lib/documents/fixtures.js';
import { account } from '#lib/ledger/fixtures.js';
import type { DocumentDetail } from '#lib/types/domain.js';
import DocumentDetailView from './document-detail.svelte';

function view(document: DocumentDetail, props = {}) {
	render(DocumentDetailView, { props: { document, ...props } });
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

	it('says where the document is booked and lists the booked entries, each opening in review', async () => {
		const onopenentry = vi.fn();
		view(
			documentDetail({
				not_booked: null,
				booking: {
					account_id: 4,
					source_transaction_id: 90,
					entries: [
						{ id: 7, source_text: 'USB cable', amount: { amount: -1500, currency: 'EUR' } },
						{ id: 8, source_text: null, amount: { amount: -3231, currency: 'EUR' } }
					]
				}
			}),
			{
				accounts: new Map([[4, account({ id: 4, name: 'Amazon clearing', kind: 'clearance' })]]),
				onopenentry
			}
		);

		expect(screen.getByRole('link', { name: 'Amazon clearing' })).toHaveAttribute(
			'href',
			'/accounts/4'
		);
		const entries = screen.getByRole('list');
		expect(within(entries).getByText('−15.00')).toBeInTheDocument();
		await fireEvent.click(within(entries).getByRole('button', { name: 'USB cable' }));
		expect(onopenentry).toHaveBeenCalledWith(7);
	});

	it('shows the reason a document is not booked', () => {
		view(
			documentDetail({
				not_booked: { reason: 'before_start', currency: 'EUR', account_id: 4, start: '2026-09-30' }
			}),
			{ accounts: new Map([[4, account({ id: 4, name: 'Amazon clearing' })]]) }
		);

		expect(
			screen.getByText('Not booked: before Amazon clearing’s start Sep 30, 2026')
		).toBeInTheDocument();
	});
});
