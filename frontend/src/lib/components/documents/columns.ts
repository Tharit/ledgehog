// The column layout of the documents list, defined once like the ledger's (components/ledger):
// the header and every row follow this list. Title is the flexible column.
export type DocumentColumnId = 'provider' | 'date' | 'reference' | 'title' | 'amount' | 'booked';

export type DocumentColumn = {
	id: DocumentColumnId;
	header: string;
	width: string;
	align?: 'right';
};

export const DOCUMENT_COLUMNS: readonly DocumentColumn[] = [
	{ id: 'provider', header: 'Provider', width: '8rem' },
	{ id: 'date', header: 'Date', width: '6.5rem' },
	{ id: 'reference', header: 'Reference', width: '9rem' },
	{ id: 'title', header: 'Title', width: 'minmax(0, 1fr)' },
	{ id: 'amount', header: 'Amount', width: '7rem', align: 'right' },
	{ id: 'booked', header: 'Booked', width: '15rem' }
];

export const DOCUMENT_GRID_TEMPLATE = DOCUMENT_COLUMNS.map((c) => c.width).join(' ');
