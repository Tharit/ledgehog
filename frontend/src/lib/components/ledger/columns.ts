// The column layout of the entry list, defined once: the header and every row (and the skeleton
// rows) follow this list, in this order. To reorder the columns, move a line. The widths are
// content-driven (patterns §4.1): each column says how it is sized, and column-sizer.svelte.ts
// measures what the rows hold; `width` is the static track used until the first measurement
// (the loading skeleton, the first paint). The description is the one column that takes the rest.

import { amountHeader } from '#lib/format/index.js';
import type { SizingColumn } from '#lib/ledger/column-sizing.js';

export type ColumnId =
	'select' | 'date' | 'account' | 'category' | 'payee' | 'description' | 'review' | 'amount';

/**
 * How a column is sized from what its cells hold: `fit` takes its widest cell and never shrinks
 * (amount, review); `flex` takes its widest cell up to a cap, and gives way to a floor; `fill`
 * takes the rest. `cap` and `floor` are in rem.
 */
export type ColumnSize =
	{ kind: 'fit' } | { kind: 'flex'; cap: number; floor: number } | { kind: 'fill'; floor: number };

export type Column = {
	id: ColumnId;
	/** the header text; `hidden` columns keep it for screen readers only */
	header: string;
	hiddenHeader?: boolean;
	/** the static CSS grid track, before anything is measured */
	width: string;
	size: ColumnSize;
	align?: 'right';
};

// patterns §4.1: the minimum of a column that gives way is 4.5rem, the description's 8rem
const FLOOR = 4.5;

export const COLUMNS: readonly Column[] = [
	{ id: 'date', header: 'Date', width: '6.5rem', size: { kind: 'fit' } },
	{
		id: 'account',
		header: 'Account',
		width: '9rem',
		size: { kind: 'flex', cap: 14, floor: FLOOR }
	},
	{
		id: 'category',
		header: 'Category',
		width: '10rem',
		size: { kind: 'flex', cap: 14, floor: FLOOR }
	},
	{ id: 'payee', header: 'Payee', width: '9rem', size: { kind: 'flex', cap: 16, floor: FLOOR } },
	{
		id: 'description',
		header: 'Description',
		width: 'minmax(0, 1fr)',
		size: { kind: 'fill', floor: 8 }
	},
	{ id: 'review', header: 'Review', hiddenHeader: true, width: '4.5rem', size: { kind: 'fit' } },
	{ id: 'amount', header: 'Amount', width: '7rem', align: 'right', size: { kind: 'fit' } }
];

/**
 * The review queue's pending section has a narrow first column of checkboxes, without a header
 * (views/review-queue.md): the sizer allocates over all of them, so the columns the other sections
 * share with it stay equally wide.
 */
export const SELECT_COLUMN: Column = {
	id: 'select',
	header: 'Select',
	hiddenHeader: true,
	width: '1rem',
	size: { kind: 'fit' }
};

/** every column the review queue's sections draw, for the one sizer they share */
export const QUEUE_COLUMNS: readonly Column[] = [SELECT_COLUMN, ...COLUMNS];

/** The ledger list's columns: its day rows carry the date (patterns §4.1), so no date column. */
export const LEDGER_COLUMNS: readonly Column[] = COLUMNS.filter((c) => c.id !== 'date');

/** The static grid-template-columns value of a column list, shared by its header and its rows. */
export function gridTemplate(columns: readonly Column[]): string {
	return columns.map((column) => column.width).join(' ');
}

/** The full column list's static grid-template-columns value. */
export const GRID_TEMPLATE = gridTemplate(COLUMNS);

/** Classes every row shares so that its cells sit on the column tracks. */
export const ROW_GRID = 'grid items-center gap-x-3';

/**
 * On a grid (or an ancestor of several), while it carries `data-measuring`: every `[data-col]`
 * cell is as wide as its content, which is what the sizer reads.
 */
export const MEASURABLE =
	'[&[data-measuring]_[data-col]]:w-max [&[data-measuring]_[data-col]]:max-w-none [&[data-measuring]_[data-col]]:justify-self-start';

/** A column's header text: the amount column names the currency its amounts share (patterns §2). */
export function columnHeader(column: Column, currency: string | null): string {
	return column.id === 'amount' ? amountHeader(column.header, currency) : column.header;
}

const REM = 16;

/** The columns as the allocator sees them, given each column's measured width in px. */
export function sizingColumns(
	columns: readonly Column[],
	measured: Readonly<Record<string, number>>
): SizingColumn[] {
	return columns.map((column): SizingColumn => {
		const { size } = column;
		if (size.kind === 'flex') {
			return {
				id: column.id,
				kind: 'flex',
				measured: measured[column.id] ?? 0,
				floor: size.floor * REM,
				cap: size.cap * REM
			};
		}
		if (size.kind === 'fill') {
			return {
				id: column.id,
				kind: 'fill',
				measured: measured[column.id] ?? 0,
				floor: size.floor * REM
			};
		}
		return {
			id: column.id,
			kind: 'fixed',
			width: measured[column.id] ?? parseFloat(column.width) * REM
		};
	});
}
