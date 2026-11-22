import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { DeleteDocumentFlow } from '#lib/documents/delete-flow.svelte.js';
import { documentDetail } from '#lib/documents/fixtures.js';
import DeleteDocumentDialog from './delete-document-dialog.svelte';

const booking = {
	account_id: 4,
	source_transaction_id: 90,
	entries: [{ id: 7, source_text: 'USB cable', amount: { amount: -1500, currency: 'EUR' } }]
};

function show(
	document = documentDetail({ not_booked: null, booking }),
	flow = new DeleteDocumentFlow()
) {
	const onclose = vi.fn();
	const ondeleted = vi.fn();
	render(DeleteDocumentDialog, {
		props: { open: true, document, accountName: 'Amazon clearing', flow, onclose, ondeleted }
	});
	return { onclose, ondeleted };
}

describe('DeleteDocumentDialog', () => {
	it('says the booking, its account and its entries go, and that the importer may deliver again', () => {
		show();
		expect(
			screen.getByText(
				/its booking on Amazon clearing with all its entries, confirmed ones included/
			)
		).toBeInTheDocument();
		expect(screen.getByText(/the email importer does so after a Reset/)).toBeInTheDocument();
	});

	it('mentions no booking for a document that is not booked', () => {
		show(documentDetail({ booking: null }));
		expect(screen.queryByText(/its booking/)).toBeNull();
		expect(screen.getByText(/The document goes/)).toBeInTheDocument();
	});

	it('reports a deletion', async () => {
		const flow = new DeleteDocumentFlow();
		vi.spyOn(flow, 'confirm').mockResolvedValue(true);
		const { ondeleted } = show(undefined, flow);
		await fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
		await waitFor(() => expect(ondeleted).toHaveBeenCalledOnce());
	});

	it('shows a failure and stays open', async () => {
		const flow = new DeleteDocumentFlow();
		vi.spyOn(flow, 'confirm').mockImplementation(async () => {
			flow.failure = { kind: 'error', text: 'This no longer exists.', retryable: false };
			return false;
		});
		const { ondeleted } = show(undefined, flow);
		await fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
		await waitFor(() => expect(screen.getByText('This no longer exists.')).toBeInTheDocument());
		expect(ondeleted).not.toHaveBeenCalled();
	});
});
