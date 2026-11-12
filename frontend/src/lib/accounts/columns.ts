// The column layout of the accounts list (ux/views/account.md), defined once: the cards of all groups
// share these tracks, so that they line up as one list. Notices is the flexible column and takes the
// remaining width; every other column has a fixed width. A depot's or asset's card carves its gain and
// return out of the notices' width, so the balance stays at the right edge, aligned with the others.
import { amountHeader } from '#lib/format/index.js';

export type ColumnId = 'account' | 'age' | 'notices' | 'gain' | 'return' | 'balance';

export type Column = {
	id: ColumnId;
	header: string;
	/** a CSS grid track */
	width: string;
	align?: 'right';
};

const ACCOUNT: Column = { id: 'account', header: 'Account', width: '15rem' };
const AGE: Column = { id: 'age', header: 'Data age', width: '12rem' };
const NOTICES: Column = { id: 'notices', header: 'Notices', width: 'minmax(0, 1fr)' };
const GAIN: Column = { id: 'gain', header: 'Gain', width: '8rem', align: 'right' };
const RETURN: Column = { id: 'return', header: 'Return', width: '7rem', align: 'right' };
const BALANCE: Column = { id: 'balance', header: 'Balance', width: '9rem', align: 'right' };

export const COLUMNS: readonly Column[] = [ACCOUNT, AGE, NOTICES, BALANCE];
export const INVESTMENT_COLUMNS: readonly Column[] = [ACCOUNT, AGE, NOTICES, GAIN, RETURN, BALANCE];

export const columnsOf = (investment: boolean): readonly Column[] =>
	investment ? INVESTMENT_COLUMNS : COLUMNS;

/** The grid-template-columns value of a column list, shared by its header, rows and total row. */
export function gridTemplate(columns: readonly Column[]): string {
	return columns.map((column) => column.width).join(' ');
}

/** A column's header text: the money columns name the currency their group shares (patterns §2). */
export function columnHeader(column: Column, currency: string | null): string {
	return column.id === 'balance' || column.id === 'gain'
		? amountHeader(column.header, currency)
		: column.header;
}
