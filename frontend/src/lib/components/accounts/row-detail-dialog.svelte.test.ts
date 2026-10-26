import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { provenance } from '#lib/accounts/fixtures.js';
import RowDetailDialog from './row-detail-dialog.svelte';

function open(props = {}) {
	const handlers = {
		onclose: vi.fn(),
		onopenreview: vi.fn(),
		onopencharge: vi.fn(),
		onmark: vi.fn(),
		onnotduplicate: vi.fn(),
		onedit: vi.fn(),
		ondelete: vi.fn(),
		onopenoriginal: vi.fn()
	};
	render(RowDetailDialog, {
		props: { open: true, status: 'ready', provenance: provenance(), ...handlers, ...props }
	});
	return handlers;
}

const names = () => screen.getAllByRole('button').map((b) => b.textContent?.trim());

describe('RowDetailDialog', () => {
	it('shows what the source said, the run it arrived in and the raw source', async () => {
		open();
		const dialog = await screen.findByRole('dialog');
		expect(within(dialog).getByText('REWE')).toBeInTheDocument();
		expect(within(dialog).getByText('Groceries')).toBeInTheDocument();
		expect(within(dialog).getByText(/Giro file/)).toBeInTheDocument();
		expect(within(dialog).getByText('What the source said')).toBeInTheDocument();
	});

	it('offers Open in review and Mark as duplicate of… on an imported row', async () => {
		const h = open();
		await screen.findByRole('dialog');
		expect(names()).toEqual(expect.arrayContaining(['Mark as duplicate of…', 'Open in review']));
		expect(screen.queryByRole('button', { name: 'Not a duplicate' })).not.toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Open in review' }));
		expect(h.onopenreview).toHaveBeenCalledWith(10);
		await fireEvent.click(screen.getByRole('button', { name: 'Mark as duplicate of…' }));
		expect(h.onmark).toHaveBeenCalled();
	});

	it('offers Not a duplicate and no Open in review on a duplicate, and names the original', async () => {
		const h = open({
			provenance: provenance({
				entry_id: null,
				duplicate_of: { id: 2, booked_on: '2026-10-09', amount: { amount: -4000, currency: 'EUR' } }
			})
		});
		await screen.findByRole('dialog');
		expect(screen.queryByRole('button', { name: 'Open in review' })).not.toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Mark as duplicate of…' })).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Not a duplicate' }));
		expect(h.onnotduplicate).toHaveBeenCalled();
		await fireEvent.click(screen.getByRole('button', { name: /duplicate of Oct 9, 2026/ }));
		expect(h.onopenoriginal).toHaveBeenCalledWith(2);
	});

	it('offers Edit and Delete… on a row entered by hand, never Mark as duplicate', async () => {
		const h = open({
			provenance: provenance({ authored: true, run: null, raw: { amount: '-40.00' } })
		});
		const dialog = await screen.findByRole('dialog');
		expect(within(dialog).getByText('Entered by hand')).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Mark as duplicate of…' })).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Delete…' }));
		expect(h.onedit).toHaveBeenCalled();
		expect(h.ondelete).toHaveBeenCalled();
	});

	it('says a row that is gone, with no actions', async () => {
		open({ status: 'missing', provenance: null });
		await screen.findByRole('dialog');
		expect(screen.getByText('This row no longer exists.')).toBeInTheDocument();
		expect(names()).not.toContain('Open in review');
	});
});

describe('RowDetailDialog: a booking', () => {
	it('says where a document booking came from and offers Open document, nothing that changes it', async () => {
		open({
			provenance: provenance({ run: null, raw: null }),
			booking: {
				kind: 'document',
				id: 31,
				provider: 'amazon',
				external_id: '304-1',
				account_id: null
			}
		});
		const dialog = await screen.findByRole('dialog');

		expect(within(dialog).getByText('Booked from amazon order 304-1')).toBeInTheDocument();
		expect(within(dialog).getByRole('link', { name: 'Open document' })).toHaveAttribute(
			'href',
			'/documents/31'
		);
		for (const name of ['Edit', 'Delete…', 'Mark as duplicate of…', 'Not a duplicate'])
			expect(screen.queryByRole('button', { name })).toBeNull();
		expect(screen.getByRole('button', { name: 'Open in review' })).toBeInTheDocument();
	});

	it('offers the charge of a counter-leg booking, named by its account', async () => {
		const h = open({
			booking: {
				kind: 'transfer',
				id: 55,
				provider: null,
				external_id: null,
				account_id: 4
			},
			bookingAccountName: 'Amazon clearing'
		});
		const dialog = await screen.findByRole('dialog');

		expect(within(dialog).getByText('Booked from Amazon clearing’s charge')).toBeInTheDocument();
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Open charge' }));
		expect(h.onopencharge).toHaveBeenCalledWith(55);
		expect(screen.queryByRole('link', { name: 'Open document' })).toBeNull();
	});
});
