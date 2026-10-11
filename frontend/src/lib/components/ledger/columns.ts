// The column layout of the ledger list, shared by the header and every row so they line up:
// date, account (only where several accounts can appear), description, payee, category, tags,
// review badges, amount (patterns §4.1). The class names are written out in full so that
// Tailwind sees them.

const WITH_ACCOUNT =
	'grid grid-cols-[6.5rem_9rem_minmax(0,2.2fr)_minmax(0,1.2fr)_minmax(0,1.6fr)_minmax(0,1.2fr)_3rem_7rem]';
const WITHOUT_ACCOUNT =
	'grid grid-cols-[6.5rem_minmax(0,2.2fr)_minmax(0,1.2fr)_minmax(0,1.6fr)_minmax(0,1.2fr)_3rem_7rem]';

export function rowGrid(showAccount: boolean): string {
	return showAccount ? WITH_ACCOUNT : WITHOUT_ACCOUNT;
}
