import { redirect } from '@sveltejs/kit';

// There is no overview yet: the ledger is the start page.
export function load() {
	redirect(307, '/ledger');
}
