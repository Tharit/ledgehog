// The column layout of the documents list, defined once like the ledger's (components/ledger):
// the header and every row follow this list. Merchant or title is the flexible column.
export type DocumentColumnId = 'provider' | 'date' | 'title' | 'amount' | 'booked';

export type DocumentColumn = {
	id: DocumentColumnId;
	header: string;
	width: string;
	align?: 'right';
};

export const DOCUMENT_COLUMNS: readonly DocumentColumn[] = [
	{ id: 'provider', header: 'Provider', width: '8rem' },
	{ id: 'date', header: 'Date', width: '6.5rem' },
	{ id: 'title', header: 'Merchant or title', width: 'minmax(0, 1fr)' },
	{ id: 'amount', header: 'Amount', width: '7rem', align: 'right' },
	{ id: 'booked', header: 'Booked', width: '15rem' }
];

export const DOCUMENT_GRID_TEMPLATE = DOCUMENT_COLUMNS.map((c) => c.width).join(' ');
