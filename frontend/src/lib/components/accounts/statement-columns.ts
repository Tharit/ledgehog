// The statement's grid, defined once: the header, the source rows, the balance markers and the
// skeleton rows follow it. The middle column takes the remaining width.
export const STATEMENT_COLUMNS = [
	{ id: 'date', header: 'Date', width: '6.5rem' },
	{ id: 'what', header: 'Counterparty and purpose', width: 'minmax(0, 1fr)' },
	{ id: 'amount', header: 'Amount', width: '7.5rem', align: 'right' },
	{ id: 'balance', header: 'Balance', width: '8.5rem', align: 'right' }
] as const;

export const STATEMENT_TEMPLATE = STATEMENT_COLUMNS.map((c) => c.width).join(' ');

export const STATEMENT_ROW = 'grid items-center gap-x-3';
