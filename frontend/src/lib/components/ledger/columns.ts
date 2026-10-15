// The column layout of the ledger list, defined once: the header and every row (and the skeleton
// rows) follow this list, in this order. To reorder the columns, move a line; to resize one,
// change its `width`. Description is the flexible column and takes the remaining width; every
// other column has a fixed width so the rows align.

export type ColumnId =
	'date' | 'account' | 'category' | 'payee' | 'tags' | 'description' | 'review' | 'amount';

export type Column = {
	id: ColumnId;
	/** the header text; `hidden` columns keep it for screen readers only */
	header: string;
	hiddenHeader?: boolean;
	/** a CSS grid track */
	width: string;
	align?: 'right';
};

export const COLUMNS: readonly Column[] = [
	{ id: 'date', header: 'Date', width: '6.5rem' },
	{ id: 'account', header: 'Account', width: '9rem' },
	{ id: 'category', header: 'Category', width: '10rem' },
	{ id: 'payee', header: 'Payee', width: '9rem' },
	{ id: 'tags', header: 'Tags', width: '12rem' },
	{ id: 'description', header: 'Description', width: 'minmax(0, 1fr)' },
	{ id: 'review', header: 'Review', hiddenHeader: true, width: '4.5rem' },
	{ id: 'amount', header: 'Amount', width: '7rem', align: 'right' }
];

/** The grid-template-columns value of a column list, shared by its header and its rows. */
export function gridTemplate(columns: readonly Column[]): string {
	return columns.map((column) => column.width).join(' ');
}

/** The ledger's grid-template-columns value. */
export const GRID_TEMPLATE = gridTemplate(COLUMNS);

/** Classes every row shares so that its cells sit on the column tracks. */
export const ROW_GRID = 'grid items-center gap-x-3';
