import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { documentDetail } from '#lib/documents/fixtures.js';
import type { DocumentDetail } from '#lib/types/domain.js';
import DocumentDetailView from './document-detail.svelte';

function view(document: DocumentDetail) {
	render(DocumentDetailView, { props: { document } });
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
});
