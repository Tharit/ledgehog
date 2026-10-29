// What the account page's layout shares with its two tabs (ux/views/account.md "Two tabs"): the
// stores it owns (the layout outlives a tab change, so the header and its reads are not fetched
// again), the row detail's address and "Fetch", which the Runs tab uses too. The Transactions tab
// registers its statement, so a dialog closing can hand focus back to the list.
import { getContext, setContext } from 'svelte';
import type { AccountDialogs } from '#lib/accounts/page-dialogs.svelte.js';
import type { AccountPageStore } from '#lib/stores/account-page.svelte.js';
import type { AccountRunsStore } from '#lib/stores/account-runs.svelte.js';

export class AccountPageContext {
	/** the statement's list, while the Transactions tab is shown */
	focusStatement: (() => void) | null = null;

	constructor(
		readonly view: AccountPageStore,
		readonly runs: AccountRunsStore,
		readonly dialogs: AccountDialogs,
		readonly openDetail: (id: number) => void,
		readonly fetchHere: (instanceId: number) => void | Promise<void>,
		readonly accountId: () => number | null
	) {}
}

const KEY = Symbol('account-page');

export function provideAccountPage(context: AccountPageContext): void {
	setContext(KEY, context);
}

export function useAccountPage(): AccountPageContext {
	return getContext<AccountPageContext>(KEY);
}
